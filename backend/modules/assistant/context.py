"""
build_context — снимок состояния приложения для инжекта в system prompt LLM.

Стратегия:
- «anchor» контекст в system prompt: то что нужно почти всегда (баланс,
  ближайшие 14 дней событий, недавние транзакции, 30-дневная статистика,
  справочники, текущий пользователь).
- Глубина по требованию — через read-tools (search_expenses,
  get_events_in_range, get_show_cast).

Оптимизации:
- Google Sheets — TTL-кеш 60 сек (баланс, актёры, спектакли). Три HTTP-запроса
  на первое сообщение, дальше — из памяти.
- Статистика 30 дней — SQL-агрегат вместо Python-цикла по всем ExpenseLog.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

from babel.dates import format_date
from sqlalchemy import func
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


FINANCE_PROJECTS = ["Театр", "Любовь Громова", "Урод", "Слепые"]
FINANCE_EXPENSE_TYPES = ["Личные траты", "Трата со счета ФоШу", "Пожертвование", "Возврат"]


# --------- Sheets TTL cache ---------
_SHEETS_CACHE: dict[str, tuple[float, Any]] = {}
_SHEETS_TTL = 60.0  # секунд


def _cached_sheets(key: str, fetcher):
    """Получить значение через TTL-кеш. fetcher() вызывается только если кеш пуст/протух."""
    now = time.time()
    hit = _SHEETS_CACHE.get(key)
    if hit and (now - hit[0] < _SHEETS_TTL):
        return hit[1]
    try:
        val = fetcher()
    except Exception as e:
        logger.warning(f"sheets fetch failed for '{key}': {e}")
        # если кеш есть — вернём просроченный (лучше устаревшее чем ничего)
        return hit[1] if hit else None
    _SHEETS_CACHE[key] = (now, val)
    return val


def _fmt_dt_ru(dt: datetime) -> str:
    return f"{format_date(dt, 'EE d MMM', locale='ru_RU')} {dt.strftime('%H:%M')}"


def _sheets_client():
    if not (GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON)):
        return None
    try:
        from sheets_client import SheetsClient
        return SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
    except Exception as e:
        logger.warning(f"SheetsClient init failed: {e}")
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
    return (
        [
            {
                "date": e.date,
                "amount": e.amount,
                "what": e.what,
                "project": e.project,
                "type": e.expense_type,
                "who": e.who,
            }
            for e in expenses
        ],
        [
            {
                "date": i.date,
                "amount": i.amount,
                "what": i.what,
                "project": i.project,
            }
            for i in incomes
        ],
    )


def _expense_stats_30d(db: Session) -> dict[str, Any]:
    """SQL-агрегат вместо Python-цикла. Median считаем отдельным быстрым запросом."""
    try:
        from modules.finance.models import ExpenseLog
    except Exception:
        return {}

    cutoff_iso = (date.today() - timedelta(days=30)).isoformat()
    q = db.query(
        func.count(ExpenseLog.id),
        func.coalesce(func.sum(ExpenseLog.amount), 0),
        func.coalesce(func.max(ExpenseLog.amount), 0),
        func.coalesce(func.avg(ExpenseLog.amount), 0),
    ).filter(ExpenseLog.date >= cutoff_iso)
    count, total, mx, avg = q.one()
    if not count:
        return {"count": 0}

    # медиана — берём отсортированный список только сумм (одно поле, быстро)
    amounts = [
        float(a) for (a,) in db.query(ExpenseLog.amount)
        .filter(ExpenseLog.date >= cutoff_iso)
        .order_by(ExpenseLog.amount)
        .all()
    ]
    mid = len(amounts) // 2
    median = amounts[mid] if len(amounts) % 2 else (amounts[mid - 1] + amounts[mid]) / 2

    return {
        "count": int(count),
        "median": int(median),
        "avg": int(avg or 0),
        "max": int(mx or 0),
        "sum": int(total or 0),
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


def _sheets_snapshot(sc) -> dict[str, Any]:
    if sc is None:
        return {"balance": None, "actor_mapping": {}, "shows": []}
    return {
        "balance": _cached_sheets("balance", sc.get_balance),
        "actor_mapping": _cached_sheets("actor_mapping", sc.get_actor_mapping) or {},
        "shows": _cached_sheets("shows", sc.get_show_names) or [],
    }


def _collect_active_polls(db: Session) -> list[dict]:
    """Активные опросы посещаемости с привязкой к событию и счётчиком голосов."""
    try:
        from modules.polling.models import Poll, PollVote
    except Exception:
        return []
    now = datetime.utcnow()
    polls = (
        db.query(Poll)
        .filter(Poll.is_active == True)  # noqa: E712
        .order_by(Poll.created_at.desc())
        .limit(10)
        .all()
    )
    result = []
    for p in polls:
        yes = db.query(PollVote).filter(PollVote.poll_id == p.id, PollVote.answer == "yes").count()
        no = db.query(PollVote).filter(PollVote.poll_id == p.id, PollVote.answer == "no").count()
        maybe = db.query(PollVote).filter(PollVote.poll_id == p.id, PollVote.answer == "maybe").count()
        event = None
        if p.calendar_event_id:
            e = db.query(CalendarEvent).filter(CalendarEvent.id == p.calendar_event_id).first()
            if e:
                event = {"id": e.id, "title": e.title, "start_iso": e.start_time.isoformat()}
        result.append({
            "id": p.id,
            "title": p.title,
            "event": event,
            "yes": yes,
            "no": no,
            "maybe": maybe,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return result


def _collect_availability_campaign(db: Session, actor_mapping: dict) -> Optional[dict]:
    """Текущая (последняя) кампания опроса занятости + список неответивших."""
    try:
        from modules.availability.models import AvailabilityCampaign
    except Exception:
        return None
    import json as _json
    campaign = db.query(AvailabilityCampaign).order_by(AvailabilityCampaign.id.desc()).first()
    if not campaign:
        return None
    show_names = []
    try:
        show_names = _json.loads(campaign.show_names or "[]")
    except Exception:
        pass

    total_voters = 0
    for poll in campaign.polls:
        total_voters += len({v.username for v in poll.votes if v.username})

    non_voters: list[str] = []
    if actor_mapping and show_names:
        try:
            from sheets_client import SheetsClient
            sc = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
            cast_usernames: set[str] = set()
            name_to_uname = {name.lower(): u for u, name in actor_mapping.items()}
            for show in show_names:
                cast = _cached_sheets(f"cast:{show}", lambda s=show: sc.get_show_cast(s)) or []
                cast_names = {n.lower() for n in cast}
                cast_usernames |= {name_to_uname[n] for n in cast_names if n in name_to_uname}
            for uname in cast_usernames:
                voted_all = True
                for poll in campaign.polls:
                    if not any(v.username and v.username.lower() == uname for v in poll.votes):
                        voted_all = False
                        break
                if not voted_all:
                    non_voters.append(uname)
        except Exception as e:
            logger.warning(f"non_voters compute failed in context: {e}")

    return {
        "id": campaign.id,
        "month": campaign.month,
        "shows": show_names,
        "polls_count": len(campaign.polls),
        "voters_count": total_voters,
        "non_voters": sorted(non_voters),
    }


def _resolve_current_user(actor_mapping: dict, *, user_id: Optional[int], username: str) -> dict:
    """Собрать блок про текущего пользователя. actor_name резолвим по username."""
    uname = (username or "").lstrip("@").lower()
    actor_name = None
    if uname and actor_mapping:
        actor_name = actor_mapping.get(uname)
    return {
        "user_id": user_id,
        "username": username or None,
        "actor_name": actor_name,
        "is_known_actor": bool(actor_name),
    }


def build_context(
    db: Session,
    *,
    user_id: Optional[int] = None,
    username: str = "",
) -> dict[str, Any]:
    """
    Компактный snapshot состояния приложения. Внешние вызовы (Sheets) —
    через TTL-кеш; при недоступности возвращаем то что есть, ошибок наружу
    не пробрасываем.
    """
    now_utc = datetime.utcnow()
    now_msk = now_utc + timedelta(hours=3)
    today_ru = format_date(now_msk, "EEEE, d MMMM y", locale="ru_RU")

    sc = _sheets_client()
    sheets = _sheets_snapshot(sc)
    actor_mapping = sheets["actor_mapping"]

    upcoming = _collect_upcoming_events(db)
    recent_exp, recent_inc = _collect_recent_transactions(db)
    stats = _expense_stats_30d(db)
    settings = _collect_settings(db)
    current_user = _resolve_current_user(actor_mapping, user_id=user_id, username=username)
    active_polls = _collect_active_polls(db)
    availability_campaign = _collect_availability_campaign(db, actor_mapping)

    return {
        "now_msk": now_msk.strftime("%Y-%m-%d %H:%M"),
        "today": today_ru,
        "balance_rub": sheets.get("balance"),
        "current_user": current_user,
        "settings": settings,
        "projects": FINANCE_PROJECTS,
        "expense_types": FINANCE_EXPENSE_TYPES,
        "shows": sheets.get("shows", []),
        "actors": [{"name": name, "username": u} for u, name in actor_mapping.items()],
        "upcoming_events": upcoming,
        "active_polls": active_polls,
        "availability_campaign": availability_campaign,
        "recent_expenses": recent_exp,
        "recent_incomes": recent_inc,
        "expense_stats_30d": stats,
    }
