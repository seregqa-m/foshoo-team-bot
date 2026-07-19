"""
build_context — снимок состояния приложения для инжекта в system prompt LLM.

Идея: одним HTTP-запросом к бэку получить всё, что нужно ассистенту чтобы
осмысленно отвечать на вопросы актёров: баланс копилки, ближайшие события,
недавние транзакции, статистика по расходам за месяц, справочники (актёры,
спектакли, проекты, типы расходов), текущие настройки авто-опросов.
Всё компактно, готово к сериализации в JSON и вкладыванию в prompt.
"""
from __future__ import annotations

import logging
import os
import statistics
from datetime import datetime, timedelta
from typing import Any, Optional

from babel.dates import format_date
from sqlalchemy.orm import Session

from config import (
    ADMIN_ID,
    GOOGLE_CALENDAR_JSON,
    GOOGLE_SHEETS_ID,
    TROUPE_FILTER,
)
from modules.calendar.models import CalendarEvent
from modules.notifications.models import NotificationSetting

logger = logging.getLogger(__name__)


# Константы из finance_router — держим их же, чтобы контекст был согласован
FINANCE_PROJECTS = ["Театр", "Любовь Громова", "Урод", "Слепые"]
FINANCE_EXPENSE_TYPES = ["Личные траты", "Трата со счета ФоШу", "Пожертвование", "Возврат"]


def _fmt_dt_ru(dt: datetime) -> str:
    """Человечная дата вида «сб 19 июл 19:00»."""
    return f"{format_date(dt, 'EE d MMM', locale='ru_RU')} {dt.strftime('%H:%M')}"


def _sheets_client():
    if not (GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON)):
        return None
    try:
        from sheets_client import SheetsClient
        return SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
    except Exception as e:
        logger.warning(f"SheetsClient init failed for context: {e}")
        return None


def _collect_upcoming_events(db: Session, days: int = 14, limit: int = 20) -> list[dict]:
    now = datetime.utcnow()
    horizon = now + timedelta(days=days)
    events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= horizon,
            CalendarEvent.is_cancelled == False,  # noqa: E712
        )
        .order_by(CalendarEvent.start_time)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "title": e.title,
            "start": _fmt_dt_ru(e.start_time),
            "start_iso": e.start_time.isoformat(),
            "end": e.end_time.strftime("%H:%M") if e.end_time else None,
            "location": e.location or None,
        }
        for e in events
    ]


def _collect_recent_transactions(db: Session, limit_exp: int = 10, limit_inc: int = 5) -> tuple[list[dict], list[dict]]:
    """Последние N расходов и M доходов из БД. БД синхронизируется с Sheets, так что источник ок."""
    try:
        from modules.finance.models import ExpenseLog, IncomeLog
    except Exception:
        return [], []

    expenses = (
        db.query(ExpenseLog)
        .order_by(ExpenseLog.date.desc(), ExpenseLog.id.desc())
        .limit(limit_exp)
        .all()
    )
    incomes = (
        db.query(IncomeLog)
        .order_by(IncomeLog.date.desc(), IncomeLog.id.desc())
        .limit(limit_inc)
        .all()
    )
    exp = [
        {
            "date": e.date,
            "amount": e.amount,
            "what": e.what,
            "project": e.project,
            "type": getattr(e, "expense_type", None),
            "who": getattr(e, "who", None),
        }
        for e in expenses
    ]
    inc = [
        {
            "date": i.date,
            "amount": i.amount,
            "what": i.what,
            "project": i.project,
        }
        for i in incomes
    ]
    return exp, inc


def _expense_stats_30d(db: Session) -> dict[str, Any]:
    try:
        from modules.finance.models import ExpenseLog
    except Exception:
        return {}

    cutoff = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
    # date у ExpenseLog хранится в формате DD.MM.YYYY согласно router, отфильтруем в Python
    rows = db.query(ExpenseLog).all()
    recent = []
    for r in rows:
        try:
            d, m, y = r.date.split(".")
            iso = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            if iso >= cutoff:
                recent.append(int(r.amount))
        except Exception:
            continue
    if not recent:
        return {"count": 0}
    return {
        "count": len(recent),
        "median": int(statistics.median(recent)),
        "max": max(recent),
        "sum": sum(recent),
    }


def _collect_settings(db: Session) -> dict[str, Any]:
    s = (
        db.query(NotificationSetting)
        .filter(NotificationSetting.user_id == ADMIN_ID)
        .first()
    )
    if not s:
        return {
            "troupe_filter": TROUPE_FILTER,
            "current_show": None,
            "poll_reminders_enabled": False,
            "reminder_days_before": None,
            "reminder_time": None,
        }
    return {
        "troupe_filter": s.troupe_filter or TROUPE_FILTER,
        "current_show": s.current_show,
        "poll_reminders_enabled": bool(s.poll_reminders_enabled),
        "reminder_days_before": s.reminder_days_before,
        "reminder_time": s.reminder_time,
    }


def _collect_sheets(sc) -> dict[str, Any]:
    if sc is None:
        return {"balance": None, "actors": [], "shows": []}
    out: dict[str, Any] = {}
    try:
        out["balance"] = sc.get_balance()
    except Exception as e:
        logger.warning(f"balance fetch failed: {e}")
        out["balance"] = None
    try:
        mapping = sc.get_actor_mapping()
        # компактно: имя + username
        out["actors"] = [{"name": name, "username": u} for u, name in mapping.items()]
    except Exception as e:
        logger.warning(f"actor mapping fetch failed: {e}")
        out["actors"] = []
    try:
        out["shows"] = sc.get_show_names()
    except Exception as e:
        logger.warning(f"show names fetch failed: {e}")
        out["shows"] = []
    return out


def build_context(db: Session, *, user_id: Optional[int] = None) -> dict[str, Any]:
    """
    Собрать компактный snapshot состояния приложения. Все внешние вызовы
    (Sheets) обёрнуты в try/except — контекст всегда возвращается, даже если
    что-то недоступно.
    """
    now_utc = datetime.utcnow()
    now_msk = now_utc + timedelta(hours=3)  # проект живёт в MSK
    today_ru = format_date(now_msk, "EEEE, d MMMM y", locale="ru_RU")

    sc = _sheets_client()
    sheets = _collect_sheets(sc)
    upcoming = _collect_upcoming_events(db)
    recent_exp, recent_inc = _collect_recent_transactions(db)
    stats = _expense_stats_30d(db)
    settings = _collect_settings(db)

    return {
        "now_msk": now_msk.strftime("%Y-%m-%d %H:%M"),
        "today": today_ru,
        "balance_rub": sheets.get("balance"),
        "settings": settings,
        "projects": FINANCE_PROJECTS,
        "expense_types": FINANCE_EXPENSE_TYPES,
        "shows": sheets.get("shows", []),
        "actors": sheets.get("actors", []),
        "upcoming_events": upcoming,
        "recent_expenses": recent_exp,
        "recent_incomes": recent_inc,
        "expense_stats_30d": stats,
        "current_user_id": user_id,
    }
