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


# ----------------------- POLLS & SETTINGS (write) ----------------------- #

async def _create_attendance_poll_handler(db: Session, args: dict, ctx: dict) -> dict:
    from modules.calendar.router import launch_poll_for_event
    event_id = int(args.get("event_id") or 0)
    if not event_id:
        raise HTTPException(status_code=400, detail="event_id обязателен")
    return await launch_poll_for_event(event_id=event_id, user_id=ctx.get("user_id"), db=db)


CREATE_ATTENDANCE_POLL = Tool(
    name="create_attendance_poll",
    description=(
        "Запустить в Telegram-группе опрос посещаемости на событие. Используй "
        "когда пользователь просит: «запусти опрос на субботу», «опроси группу "
        "про репетицию». Event_id ищи в CONTEXT.upcoming_events. Один активный "
        "опрос на событие."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "create_attendance_poll",
            "description": "Создать опрос посещаемости на событие. Требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer", "description": "ID события из CONTEXT.upcoming_events[i].id"},
                },
                "required": ["event_id"],
            },
        },
    },
    handler=_create_attendance_poll_handler,
    safety_level="confirm",
    preview_builder=lambda args: {
        "title": "Запустить опрос посещаемости",
        "lines": [f"Событие #{args.get('event_id')} — уточни ниже что там за занятие"],
        "warnings": ["Опрос уйдёт всем в Telegram-группу"],
    },
)


async def _stop_poll_handler(db: Session, args: dict, ctx: dict) -> dict:
    from modules.polling.router import stop_poll as stop_poll_ep
    poll_id = int(args.get("poll_id") or 0)
    if not poll_id:
        raise HTTPException(status_code=400, detail="poll_id обязателен")
    return await stop_poll_ep(poll_id=poll_id, db=db)


STOP_POLL = Tool(
    name="stop_poll",
    description=(
        "Остановить активный опрос посещаемости. Poll_id ищи в "
        "CONTEXT.active_polls."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "stop_poll",
            "description": "Остановить опрос в Telegram и пометить неактивным. Требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "poll_id": {"type": "integer", "description": "ID опроса из CONTEXT.active_polls[i].id"},
                },
                "required": ["poll_id"],
            },
        },
    },
    handler=_stop_poll_handler,
    safety_level="confirm",
    preview_builder=lambda args: {
        "title": f"Остановить опрос #{args.get('poll_id')}",
        "lines": ["Опрос закроется в Telegram и станет неактивным"],
        "warnings": [],
    },
)


async def _create_availability_campaign_handler(db: Session, args: dict, ctx: dict) -> dict:
    from modules.availability.router import CreateCampaignRequest, create_campaign
    show_names = args.get("show_names") or []
    event_ids = args.get("event_ids") or []
    if not show_names or not event_ids:
        raise HTTPException(status_code=400, detail="show_names и event_ids обязательны")
    req = CreateCampaignRequest(show_names=list(show_names), event_ids=[int(x) for x in event_ids])
    return await create_campaign(req=req, db=db)


CREATE_AVAILABILITY_CAMPAIGN = Tool(
    name="create_availability_campaign",
    description=(
        "Запустить ежемесячный опрос занятости на следующий месяц. "
        "show_names — список спектаклей из CONTEXT.shows (обычно те что «в "
        "работе»). event_ids — даты из CONTEXT.upcoming_events (или получи "
        "полный список через get_events_in_range на следующий месяц). "
        "Старая кампания удалится."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "create_availability_campaign",
            "description": "Создать новую кампанию опроса занятости. Требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "show_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список названий спектаклей из CONTEXT.shows",
                    },
                    "event_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "ID событий (даты). До 20.",
                    },
                },
                "required": ["show_names", "event_ids"],
            },
        },
    },
    handler=_create_availability_campaign_handler,
    safety_level="confirm",
    preview_builder=lambda args: {
        "title": "Опрос занятости",
        "lines": [
            f"Спектакли: {', '.join(args.get('show_names') or [])}",
            f"Дат: {len(args.get('event_ids') or [])}",
        ],
        "warnings": [
            "Старая кампания опроса будет удалена",
            "Новые опросы уйдут в Telegram-группу (батчами по 10)",
        ],
    },
)


async def _ping_non_voters_handler(db: Session, args: dict, ctx: dict) -> dict:
    from modules.availability.router import ping_non_voters as ping_ep
    return await ping_ep(db=db)


PING_NON_VOTERS = Tool(
    name="ping_non_voters",
    description=(
        "Опубликовать в группе тег для актёров, кто ещё не ответил на текущий "
        "опрос занятости. Действует только если есть активная кампания."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "ping_non_voters",
            "description": "Публичный пинг в Telegram-группе. Требует подтверждения.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    handler=_ping_non_voters_handler,
    safety_level="confirm",
    preview_builder=lambda args: {
        "title": "Пингануть в группе неответивших",
        "lines": ["Список неответивших — в CONTEXT.availability_campaign.non_voters"],
        "warnings": ["Публичное упоминание в Telegram-группе"],
    },
)


async def _update_settings_handler(db: Session, args: dict, ctx: dict) -> dict:
    from config import ADMIN_ID
    from modules.notifications.router import (
        UpdateSettingsRequest,
        update_notification_settings,
    )
    payload = {k: v for k, v in args.items() if k in {
        "poll_reminders_enabled",
        "reminder_days_before",
        "reminder_time",
        "current_show",
        "troupe_filter",
    } and v is not None}
    if not payload:
        raise HTTPException(status_code=400, detail="Нечего обновлять")
    req = UpdateSettingsRequest(**payload)
    return await update_notification_settings(request=req, user_id=ADMIN_ID, db=db)


UPDATE_SETTINGS = Tool(
    name="update_settings",
    description=(
        "Обновить глобальные настройки приложения. Передавай ТОЛЬКО те поля, "
        "которые меняются. current_show — название репетируемого спектакля из "
        "CONTEXT.shows (пингуются только его актёры)."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "update_settings",
            "description": "Изменить глобальные настройки авто-опросов и труппы. Требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "poll_reminders_enabled": {"type": "boolean", "description": "Вкл/выкл авто-опросы посещаемости"},
                    "reminder_days_before": {"type": "integer", "description": "За сколько дней до события создавать опрос (1-7)"},
                    "reminder_time": {"type": "string", "description": "Время создания опроса, формат HH:MM (МСК)"},
                    "current_show": {"type": "string", "description": "Название текущего репетируемого спектакля из CONTEXT.shows, или пустая строка чтобы сбросить"},
                    "troupe_filter": {"type": "string", "description": "Подстрока в названии события для фильтра (например 'труппа 1')"},
                },
                "required": [],
            },
        },
    },
    handler=_update_settings_handler,
    safety_level="confirm",
    preview_builder=lambda args: {
        "title": "Обновить настройки",
        "lines": [f"{k} → {v}" for k, v in args.items() if v is not None] or ["без изменений"],
        "warnings": ["Настройки применяются ко всей группе"],
    },
)


# ----------------------- EXTERNAL POLL IMPORT ----------------------- #

async def _get_external_poll_handler(db: Session, args: dict, ctx: dict) -> dict:
    """Прочитать сохранённые внешние опросы и сопоставить варианты с событиями БД."""
    import json as _json
    from modules.availability.models import ExternalPoll

    polls = (
        db.query(ExternalPoll)
        .order_by(ExternalPoll.seen_at.desc())
        .limit(10)
        .all()
    )
    if not polls:
        return {"error": "Ни одного внешнего опроса не найдено. Бот сохраняет опросы автоматически когда видит их в группе."}

    # Загружаем события ближайших 90 дней для сопоставления
    now = datetime.utcnow()
    events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.start_time >= now - timedelta(days=30),
            CalendarEvent.start_time <= now + timedelta(days=90),
            CalendarEvent.is_cancelled == False,  # noqa: E712
        )
        .order_by(CalendarEvent.start_time)
        .all()
    )

    def _match_option_to_event(text: str):
        """Попытаться распарсить дату из текста варианта и найти событие."""
        import re
        _MONTHS_RU = {
            "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5,
            "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
        }
        # ищем день + месяц, опционально время
        m = re.search(r"(\d{1,2})\s+([а-яё]{3,4})(?:\s+(\d{1,2}):(\d{2}))?", text.lower())
        if not m:
            return None
        day = int(m.group(1))
        month_word = m.group(2)[:3]
        month = _MONTHS_RU.get(month_word)
        if not month:
            return None
        hour = int(m.group(3)) if m.group(3) else None
        minute = int(m.group(4)) if m.group(4) else None

        for e in events:
            dt = e.start_time
            if dt.day == day and dt.month == month:
                if hour is None or (dt.hour == hour and dt.minute == minute):
                    return {"event_id": e.id, "title": e.title, "start_iso": dt.isoformat()}
        return None

    result = []
    for poll in polls:
        options_raw = _json.loads(poll.options_json or "[]")
        options_enriched = []
        for opt in options_raw:
            matched = _match_option_to_event(opt["text"])
            options_enriched.append({
                "index": opt["index"],
                "text": opt["text"],
                "matched_event": matched,
            })
        result.append({
            "id": poll.id,
            "telegram_poll_id": poll.telegram_poll_id,
            "question": poll.question,
            "seen_at": poll.seen_at.isoformat() if poll.seen_at else None,
            "source_message_id": poll.source_message_id,
            "allows_multiple": poll.allows_multiple,
            "options": options_enriched,
        })

    return {"polls": result}


GET_EXTERNAL_POLL = Tool(
    name="get_external_poll",
    description=(
        "Прочитать Telegram-опросы, которые участники отправляли в группу. "
        "Возвращает список сохранённых опросов с вариантами ответов и сопоставлением "
        "с событиями в базе. Используй перед записью результатов вручную — чтобы "
        "понять какие даты в опросе и получить event_id для record_availability_results."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "get_external_poll",
            "description": "Получить сохранённые внешние Telegram-опросы из группы.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    handler=_get_external_poll_handler,
    safety_level="read",
)


async def _record_availability_handler(db: Session, args: dict, ctx: dict) -> dict:
    import json as _json
    import os
    from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    from modules.availability.models import AvailabilityCampaign, AvailabilityVote

    entries = args.get("entries", [])
    if not entries:
        return {"error": "нет записей"}

    campaign = (
        db.query(AvailabilityCampaign)
        .order_by(AvailabilityCampaign.id.desc())
        .first()
    )

    sc = None
    if GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON):
        from sheets_client import SheetsClient
        sc = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)

    written = 0
    errors = []
    usernames_seen: set[str] = set()

    for entry in entries:
        username = (entry.get("username") or "").lstrip("@").strip().lower()
        event_id = entry.get("event_id")
        answer = entry.get("answer")

        if not username or not event_id or answer not in ("yes", "no"):
            errors.append(f"неверная запись: {entry}")
            continue

        event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
        if not event:
            errors.append(f"событие {event_id} не найдено")
            continue

        if sc:
            try:
                sc.record_poll_answer(username, event.start_time, answer)
                written += 1
                usernames_seen.add(username)
            except Exception as e:
                errors.append(f"@{username} {event_id}: {e}")

    # Отметить как проголосовавших в текущей кампании
    if campaign and usernames_seen:
        for username in usernames_seen:
            for poll in campaign.polls:
                existing = (
                    db.query(AvailabilityVote)
                    .filter(
                        AvailabilityVote.poll_id == poll.id,
                        AvailabilityVote.username == username,
                    )
                    .first()
                )
                if not existing:
                    db.add(AvailabilityVote(
                        poll_id=poll.id,
                        user_id=0,
                        username=username,
                    ))
        db.commit()

    return {
        "written": written,
        "actors": len(usernames_seen),
        "errors": errors or None,
    }


def _record_availability_preview(args: dict) -> dict:
    entries = args.get("entries", [])
    by_user: dict[str, dict] = {}
    for e in entries:
        u = (e.get("username") or "?").lstrip("@")
        by_user.setdefault(u, {"yes": 0, "no": 0})
        a = e.get("answer", "")
        if a in ("yes", "no"):
            by_user[u][a] += 1

    lines = []
    for u, counts in by_user.items():
        parts = []
        if counts["yes"]:
            parts.append(f"может: {counts['yes']}")
        if counts["no"]:
            parts.append(f"не может: {counts['no']}")
        lines.append(f"@{u}: {', '.join(parts)}")

    return {
        "title": f"Записать результаты занятости ({len(entries)} записей, {len(by_user)} актёров)",
        "lines": lines[:20],
        "warnings": ["Данные будут записаны в Google Sheets «График [составы]»"],
    }


RECORD_AVAILABILITY_RESULTS = Tool(
    name="record_availability_results",
    description=(
        "Вручную записать результаты опроса занятости в Google Sheets и отметить актёров "
        "как проголосовавших. Используй после get_external_poll — когда уже знаешь event_id "
        "для каждой даты и usernames актёров."
    ),
    schema={
        "type": "function",
        "function": {
            "name": "record_availability_results",
            "description": "Записать результаты опроса занятости вручную. Требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "description": "Список записей: кто, на какое событие, какой ответ",
                        "items": {
                            "type": "object",
                            "properties": {
                                "username": {"type": "string", "description": "Telegram username (без @)"},
                                "event_id": {"type": "integer", "description": "ID события из calendar_events"},
                                "answer": {"type": "string", "enum": ["yes", "no"], "description": "yes = может, no = не может"},
                            },
                            "required": ["username", "event_id", "answer"],
                        },
                    },
                },
                "required": ["entries"],
            },
        },
    },
    handler=_record_availability_handler,
    safety_level="confirm",
    preview_builder=_record_availability_preview,
)


# ----------------------- REGISTRY ----------------------- #

async def _upload_afisha_handler(db: Session, args: dict, ctx: dict) -> dict:
    # Загрузка файла происходит на фронте напрямую в /api/afisha/upload.
    # Этот путь не должен вызываться через /execute.
    return {"message": "Загрузи файл через карточку выше"}


UPLOAD_AFISHA = Tool(
    name="upload_afisha",
    description="Открыть форму загрузки новой афиши на сайт foshoo-theatre.ru. "
                "Текущая афиша станет архивной. Вызывай когда пользователь просит обновить, загрузить или заменить афишу.",
    schema={
        "type": "function",
        "function": {
            "name": "upload_afisha",
            "description": "Открыть форму загрузки новой афиши на сайт.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    handler=_upload_afisha_handler,
    safety_level="confirm",
    preview_builder=lambda args: {
        "title": "Обновить афишу на сайте",
        "lines": [
            "Текущая афиша (afisha-new) станет архивной (afisha-old).",
            "Выбери файл с новой афишей — изображение или PDF.",
        ],
        "warnings": [],
    },
)


TOOLS: dict[str, Tool] = {
    t.name: t for t in [
        # write, требуют confirm
        ADD_EXPENSE, ADD_INCOME, CREATE_EVENT, UPDATE_EVENT,
        CREATE_ATTENDANCE_POLL, STOP_POLL, CREATE_AVAILABILITY_CAMPAIGN,
        PING_NON_VOTERS, UPDATE_SETTINGS, UPLOAD_AFISHA,
        RECORD_AVAILABILITY_RESULTS,
        # read, исполняются сразу
        SEARCH_EXPENSES, GET_EVENTS_IN_RANGE, GET_SHOW_CAST, GET_EXTERNAL_POLL,
    ]
}


def get_tool_schemas() -> list[dict]:
    """Список tool-schemas в формате, который принимает OpenAI-совместимый API."""
    return [t.schema for t in TOOLS.values()]


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name)
