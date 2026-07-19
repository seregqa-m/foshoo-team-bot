"""
Реестр tools для function calling ассистента.

Каждый tool = JSON Schema (для LLM) + async handler (для исполнения).
Все текущие tools — «write» и требуют явного подтверждения пользователем:
LLM возвращает tool_call → бэк формирует action_token (JWT со всеми
аргументами) → фронт показывает preview → пользователь [Выполнить] →
POST /api/assistant/execute вызывает handler.

Deletions/mass-updates намеренно отсутствуют в реестре.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from config import GOOGLE_CALENDAR_ID
from modules.calendar.google_client import GoogleCalendarClient
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
    preview_builder: Callable[[dict], dict]  # args -> {title, lines: [str], warnings: [str]}


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
)


# ----------------------- REGISTRY ----------------------- #

TOOLS: dict[str, Tool] = {
    t.name: t for t in [ADD_EXPENSE, ADD_INCOME, CREATE_EVENT, UPDATE_EVENT]
}


def get_tool_schemas() -> list[dict]:
    """Список tool-schemas в формате, который принимает OpenAI-совместимый API."""
    return [t.schema for t in TOOLS.values()]


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name)
