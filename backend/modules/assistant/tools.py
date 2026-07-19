"""
Реестр tools для function calling ассистента.

Каждый tool = JSON Schema (для LLM) + async handler + safety_level.

- safety_level="read"    — исполняется сразу, результат возвращается модели
                           в tool-turn'е, диалог продолжается автоматически.
- safety_level="confirm" — НЕ исполняется. Бэк формирует action_token (JWT)
                           и preview, фронт показывает карточку, пользователь
                           жмёт [Выполнить] → POST /api/assistant/execute.

Deletions/mass-updates отсутствуют в реестре.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from config import GOOGLE_CALENDAR_ID
from modules.calendar.google_client import GoogleCalendarClient
from modules.calendar.models import CalendarEvent
from modules.calendar.services import CalendarService

logger = logging.getLogger(__name__)


ToolHandler = Callable[[Session, dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]
# сигнатура: (db, args_from_llm, user_context) -> result_dict


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: ToolHandler
    safety_level: str = "confirm"  # "read" | "confirm"
    preview_builder: Optional[Callable[[dict], dict]] = None  # обязателен для confirm


# ----------------------- FINANCE ----------------------- #

def _finance_preview(args: dict) -> dict:
    amt = args.get("amount")
    what = args.get("what") or "—"
    project = args.get("project") or "—"
    exp_type = args.get("expense_type")
    who = args.get("who") or ""
    date_str = args.get("date") or "сегодня"
    lines = [
        f"Сумма: {amt} ₽",
        f"На что: {what}",
        f"Проект: {project}",
    ]
    if exp_type:
        lines.append(f"Тип: {exp_type}")
    if who:
        lines.append(f"Кто: {who}")
    lines.append(f"Дата: {date_str}")
    return {"title": "Добавить расход" if exp_type else "Добавить доход", "lines": lines, "warnings": []}


async def _add_expense_handler(db: Session, args: dict, ctx: dict) -> dict:
    from finance_router import (  # noqa: локальный импорт чтобы не тянуть при старте
        EXPENSE_TYPES,
        ExpenseRequest,
        PROJECTS,
        add_expense as add_expense_ep,
    )
    project = args.get("project")
    if project not in PROJECTS:
        raise HTTPException(status_code=400, detail=f"Неизвестный проект: {project}")
    exp_type = args.get("expense_type")
    if exp_type not in EXPENSE_TYPES:
        raise HTTPException(status_code=400, detail=f"Неизвестный тип расхода: {exp_type}")

    username = ctx.get("username") or ""
    who = args.get("who") or ""

    req = ExpenseRequest(
        project=project,
        amount=str(args.get("amount", "")),
        what=str(args.get("what", "")).strip(),
        expense_type=exp_type,
        comment=str(args.get("comment", "")).strip(),
        username=username,
        who=who,
        date=str(args.get("date", "")).strip(),
    )
    return await add_expense_ep(req, db)


async def _add_income_handler(db: Session, args: dict, ctx: dict) -> dict:
    from finance_router import IncomeRequest, PROJECTS, add_income as add_income_ep
    project = args.get("project")
    if project not in PROJECTS:
        raise HTTPException(status_code=400, detail=f"Неизвестный проект: {project}")

    req = IncomeRequest(
        project=project,
        amount=str(args.get("amount", "")),
        what=str(args.get("what", "")).strip(),
        comment=str(args.get("comment", "")).strip(),
        date=str(args.get("date", "")).strip(),
    )
    return await add_income_ep(req, db)


ADD_EXPENSE = Tool(
    name="add_expense",
    description=(
        "Добавить расход в копилку. Используй, когда пользователь описывает "
        "разовую трату («потратил X на Y»). Проект и тип расхода бери из "
        "справочников в CONTEXT.projects и CONTEXT.expense_types."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "add_expense",
            "description": (
                "Добавить строку расхода в Google Sheets и БД. Всегда требует "
                "подтверждения пользователем."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "Сумма в рублях, целое положительное"},
                    "what": {"type": "string", "description": "На что потрачено (2-6 слов)"},
                    "project": {"type": "string", "description": "Проект из CONTEXT.projects"},
                    "expense_type": {"type": "string", "description": "Тип расхода из CONTEXT.expense_types"},
                    "who": {"type": "string", "description": "Кто потратил (полное имя актёра). Если не указано — можно оставить пусто, бэк подставит из username."},
                    "comment": {"type": "string", "description": "Опциональный комментарий"},
                    "date": {"type": "string", "description": "Дата DD.MM.YYYY. Если сегодня — оставь пустой строкой."},
                },
                "required": ["amount", "what", "project", "expense_type"],
            },
        },
    },
    handler=_add_expense_handler,
    preview_builder=_finance_preview,
    safety_level="confirm",
)

ADD_INCOME = Tool(
    name="add_income",
    description=(
        "Добавить доход в копилку. Используй когда пользователь описывает "
        "поступление денег («получили X от Y», «продали билеты на N»)."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "add_income",
            "description": "Добавить строку дохода в Google Sheets и БД. Всегда требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "Сумма в рублях, целое положительное"},
                    "what": {"type": "string", "description": "Источник (2-6 слов)"},
                    "project": {"type": "string", "description": "Проект из CONTEXT.projects"},
                    "comment": {"type": "string", "description": "Опциональный комментарий"},
                    "date": {"type": "string", "description": "Дата DD.MM.YYYY. Пусто = сегодня."},
                },
                "required": ["amount", "what", "project"],
            },
        },
    },
    handler=_add_income_handler,
    safety_level="confirm",
    preview_builder=lambda args: {
        "title": "Добавить доход",
        "lines": [
            f"Сумма: {args.get('amount')} ₽",
            f"Источник: {args.get('what') or '—'}",
            f"Проект: {args.get('project') or '—'}",
            f"Дата: {args.get('date') or 'сегодня'}",
        ],
        "warnings": [],
    },
)


# ----------------------- CALENDAR ----------------------- #

def _event_preview(args: dict) -> dict:
    title = args.get("title") or "—"
    start = args.get("start_time") or "—"
    end = args.get("end_time") or "—"
    loc = args.get("location")
    lines = [f"Название: {title}", f"Начало: {start}", f"Конец: {end}"]
    if loc:
        lines.append(f"Место: {loc}")
    return {"title": "Создать событие", "lines": lines, "warnings": []}


def _event_update_preview(args: dict) -> dict:
    ev_id = args.get("event_id")
    changes = []
    for k, label in (
        ("title", "Название"),
        ("start_time", "Начало"),
        ("end_time", "Конец"),
        ("location", "Место"),
        ("description", "Описание"),
    ):
        v = args.get(k)
        if v:
            changes.append(f"{label} → {v}")
    return {
        "title": f"Обновить событие #{ev_id}",
        "lines": changes or ["без изменений"],
        "warnings": ["Изменение попадёт в Google Calendar всех участников"],
    }


def _google_client() -> Optional[GoogleCalendarClient]:
    from config import GOOGLE_CALENDAR_JSON
    import os
    if not (os.path.exists(GOOGLE_CALENDAR_JSON) and GOOGLE_CALENDAR_ID):
        return None
    try:
        return GoogleCalendarClient(GOOGLE_CALENDAR_JSON)
    except Exception as e:
        logger.error(f"GoogleCalendarClient init failed: {e}")
        return None


async def _create_event_handler(db: Session, args: dict, ctx: dict) -> dict:
    gc = _google_client()
    if not gc:
        raise HTTPException(status_code=503, detail="Google Calendar не настроен")
    try:
        start = datetime.fromisoformat(str(args["start_time"]))
        end = datetime.fromisoformat(str(args["end_time"]))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат даты: {e}")

    service = CalendarService(db, gc)
    return service.create_event(
        calendar_id=GOOGLE_CALENDAR_ID,
        title=str(args["title"]),
        start_time=start,
        end_time=end,
        location=str(args.get("location") or ""),
        description=str(args.get("description") or ""),
    )


async def _update_event_handler(db: Session, args: dict, ctx: dict) -> dict:
    gc = _google_client()
    if not gc:
        raise HTTPException(status_code=503, detail="Google Calendar не настроен")
    event_id = args.get("event_id")
    if not event_id:
        raise HTTPException(status_code=400, detail="event_id обязателен")

    start = None
    end = None
    try:
        if args.get("start_time"):
            start = datetime.fromisoformat(str(args["start_time"]))
        if args.get("end_time"):
            end = datetime.fromisoformat(str(args["end_time"]))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат даты: {e}")

    service = CalendarService(db, gc)
    return service.update_event(
        calendar_id=GOOGLE_CALENDAR_ID,
        event_id=int(event_id),
        title=args.get("title"),
        start_time=start,
        end_time=end,
        location=args.get("location"),
        description=args.get("description"),
    )


CREATE_EVENT = Tool(
    name="create_event",
    description=(
        "Создать новое событие в Google Calendar. Используй когда пользователь "
        "просит добавить репетицию/спектакль/лабу. Всегда требуй уточнения даты, "
        "времени начала и конца, если не сказано явно."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Создать событие в календаре. Требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Название события (например «труппа 1 репетиция»)"},
                    "start_time": {"type": "string", "description": "ISO 8601 (например 2026-07-20T19:00:00)"},
                    "end_time": {"type": "string", "description": "ISO 8601"},
                    "location": {"type": "string", "description": "Место, опционально"},
                    "description": {"type": "string", "description": "Описание, опционально"},
                },
                "required": ["title", "start_time", "end_time"],
            },
        },
    },
    handler=_create_event_handler,
    preview_builder=_event_preview,
    safety_level="confirm",
)

UPDATE_EVENT = Tool(
    name="update_event",
    description=(
        "Обновить существующее событие. Используй для «перенеси занятие», "
        "«поменяй место», «сдвинь на час позже». event_id ищи в "
        "CONTEXT.upcoming_events по совпадению названия/даты. Передавай "
        "ТОЛЬКО те поля, которые меняются."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "Обновить событие в календаре. Требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer", "description": "ID события из CONTEXT.upcoming_events[i].id"},
                    "title": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO 8601"},
                    "end_time": {"type": "string", "description": "ISO 8601"},
                    "location": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["event_id"],
            },
        },
    },
    handler=_update_event_handler,
    preview_builder=_event_update_preview,
    safety_level="confirm",
)


# ----------------------- READ TOOLS ----------------------- #
# Исполняются немедленно, результат идёт обратно в модель tool-turn'ом.

async def _search_expenses_handler(db: Session, args: dict, ctx: dict) -> dict:
    from modules.finance.models import ExpenseLog
    q = (args.get("query") or "").strip().lower()
    days_back = int(args.get("days_back") or 90)
    project = (args.get("project") or "").strip()
    limit = min(int(args.get("limit") or 20), 50)

    cutoff_iso = (date.today() - timedelta(days=days_back)).isoformat()
    query = db.query(ExpenseLog).filter(ExpenseLog.date >= cutoff_iso)
    if project:
        query = query.filter(ExpenseLog.project == project)
    if q:
        # что и комментарий
        from sqlalchemy import or_, func
        query = query.filter(or_(
            func.lower(ExpenseLog.what).like(f"%{q}%"),
            func.lower(ExpenseLog.comment).like(f"%{q}%"),
        ))
    rows = query.order_by(ExpenseLog.date.desc(), ExpenseLog.id.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "expenses": [
            {
                "date": r.date,
                "amount": r.amount,
                "what": r.what,
                "project": r.project,
                "type": r.expense_type,
                "who": r.who,
                "comment": r.comment or "",
            }
            for r in rows
        ],
    }


SEARCH_EXPENSES = Tool(
    name="search_expenses",
    description=(
        "Найти расходы в истории. Используй, когда пользователь спрашивает "
        "«сколько мы тратили на X», «покажи все траты за апрель», «расходы "
        "проекта Урод». В CONTEXT.recent_expenses только 10 последних — эта "
        "функция для более глубокой истории."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "search_expenses",
            "description": "Поиск в истории расходов. Возвращает до 50 совпадений.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Подстрока для поиска по 'что' и комментарию. Пусто = не фильтровать."},
                    "days_back": {"type": "integer", "description": "Глубина в днях от сегодня. По умолчанию 90."},
                    "project": {"type": "string", "description": "Проект из CONTEXT.projects. Пусто = все."},
                    "limit": {"type": "integer", "description": "Максимум строк, до 50. По умолчанию 20."},
                },
                "required": [],
            },
        },
    },
    handler=_search_expenses_handler,
    safety_level="read",
)


async def _get_events_in_range_handler(db: Session, args: dict, ctx: dict) -> dict:
    from_iso = args.get("from_date")
    to_iso = args.get("to_date")
    title_q = (args.get("title_contains") or "").strip().lower()
    if not from_iso or not to_iso:
        raise HTTPException(status_code=400, detail="from_date и to_date обязательны (YYYY-MM-DD)")
    try:
        start = datetime.fromisoformat(from_iso)
        end = datetime.fromisoformat(to_iso) + timedelta(days=1)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Неверный формат даты: {e}")

    q = db.query(CalendarEvent).filter(
        CalendarEvent.start_time >= start,
        CalendarEvent.start_time < end,
        CalendarEvent.is_cancelled == False,  # noqa
    )
    if title_q:
        from sqlalchemy import func
        q = q.filter(func.lower(CalendarEvent.title).like(f"%{title_q}%"))
    rows = q.order_by(CalendarEvent.start_time).limit(100).all()
    return {
        "count": len(rows),
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "start": e.start_time.isoformat(),
                "end": e.end_time.isoformat() if e.end_time else None,
                "location": e.location,
            }
            for e in rows
        ],
    }


GET_EVENTS_IN_RANGE = Tool(
    name="get_events_in_range",
    description=(
        "Получить события календаря в произвольном диапазоне дат. Используй, "
        "когда пользователь спрашивает про события вне 14-дневного окна "
        "CONTEXT.upcoming_events («что было в апреле», «покажи все репетиции "
        "Урода за месяц»)."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "get_events_in_range",
            "description": "События за диапазон дат. До 100 штук.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "description": "YYYY-MM-DD включительно"},
                    "to_date": {"type": "string", "description": "YYYY-MM-DD включительно"},
                    "title_contains": {"type": "string", "description": "Подстрока в названии. Пусто = все."},
                },
                "required": ["from_date", "to_date"],
            },
        },
    },
    handler=_get_events_in_range_handler,
    safety_level="read",
)


async def _get_show_cast_handler(db: Session, args: dict, ctx: dict) -> dict:
    from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    import os
    show_name = (args.get("show_name") or "").strip()
    if not show_name:
        raise HTTPException(status_code=400, detail="show_name обязателен")
    if not (GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON)):
        return {"show": show_name, "cast": [], "error": "Google Sheets не настроен"}
    try:
        from sheets_client import SheetsClient
        sc = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        cast = sc.get_show_cast(show_name)
        return {"show": show_name, "cast": cast, "count": len(cast)}
    except Exception as e:
        logger.error(f"get_show_cast failed: {e}")
        return {"show": show_name, "cast": [], "error": str(e)[:200]}


GET_SHOW_CAST = Tool(
    name="get_show_cast",
    description=(
        "Получить состав конкретного спектакля из Google Sheets. Названия "
        "спектаклей — в CONTEXT.shows. Используй, когда спрашивают «кто "
        "играет в X», «состав Урода»."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "get_show_cast",
            "description": "Список актёров, задействованных в спектакле.",
            "parameters": {
                "type": "object",
                "properties": {
                    "show_name": {"type": "string", "description": "Точное название спектакля из CONTEXT.shows"},
                },
                "required": ["show_name"],
            },
        },
    },
    handler=_get_show_cast_handler,
    safety_level="read",
)


# ----------------------- REGISTRY ----------------------- #

TOOLS: dict[str, Tool] = {
    t.name: t for t in [
        # write, требуют confirm
        ADD_EXPENSE, ADD_INCOME, CREATE_EVENT, UPDATE_EVENT,
        # read, исполняются сразу
        SEARCH_EXPENSES, GET_EVENTS_IN_RANGE, GET_SHOW_CAST,
    ]
}


def get_tool_schemas() -> list[dict]:
    """Список tool-schemas в формате, который принимает OpenAI-совместимый API."""
    return [t.schema for t in TOOLS.values()]


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name)
