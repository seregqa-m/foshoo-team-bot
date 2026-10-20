"""Google is authoritative for both an occurrence and its recurring parent."""
import logging
from datetime import datetime

from fastapi import HTTPException
from googleapiclient.errors import HttpError

from config import TIMEZONE
from core.time import as_local, local_now
from .models import CalendarEvent

logger = logging.getLogger(__name__)


def target_event(service, calendar_id, event_id, scope):
    row = service.get_event_by_id(event_id)
    if not row or row.is_cancelled or not row.google_event_id:
        raise HTTPException(404, "Событие не найдено или отменено")
    instance = service.google_client.get_event(calendar_id, row.google_event_id)
    if instance.get("status") == "cancelled":
        raise HTTPException(409, "Событие отменено в Google Calendar. Обновите расписание.")
    parent_id = instance.get("recurringEventId")
    recurring = bool(parent_id or instance.get("recurrence"))
    if scope == "series":
        if not recurring:
            raise HTTPException(400, "Это событие не входит в повторяющуюся серию")
        target = service.google_client.get_event(calendar_id, parent_id) if parent_id else instance
    elif scope == "single":
        target = instance
    else:
        raise HTTPException(400, "Неизвестная область изменения")
    if target.get("status") == "cancelled":
        raise HTTPException(409, "Серия отменена в Google Calendar. Обновите расписание.")
    return row, target, recurring


def editor_data(service, calendar_id, event_id, scope="single"):
    _, target, recurring = target_event(service, calendar_id, event_id, scope)
    return {
        "scope": scope,
        "is_recurring": recurring,
        "etag": target["etag"],
        "title": target.get("summary", ""),
        "location": target.get("location", ""),
        "description": target.get("description", ""),
        "all_day": "date" in target["start"],
        "start_time": target["start"].get("dateTime") or target["start"]["date"],
        "end_time": target["end"].get("dateTime") or target["end"]["date"],
    }


def update_google_event(service, calendar_id, event_id, *, scope="single", expected_etag=None,
                        title=None, start_time=None, end_time=None, location=None, description=None):
    row, current, _ = target_event(service, calendar_id, event_id, scope)
    if expected_etag is not None and current["etag"] != expected_etag:
        raise HTTPException(409, "Событие изменили в Google Calendar. Откройте форму заново.")
    if scope == "series" and not expected_etag:
        raise HTTPException(409, "Откройте форму серии заново перед сохранением.")

    start = as_local(start_time) if start_time else service._parse_dt(current["start"])
    end = as_local(end_time) if end_time else service._parse_dt(current["end"])
    if end <= start:
        raise ValueError("Конец события должен быть позже начала")
    if "date" in current["start"] and end.date() <= start.date():
        raise ValueError("Конец события на весь день должен быть позже даты начала")
    patch = {}
    for key, value in (("summary", title), ("location", location), ("description", description)):
        if value is not None:
            if key == "summary" and not value.strip():
                raise ValueError("Укажите название события")
            patch[key] = value
    for key, value, supplied in (("start", start, start_time), ("end", end, end_time)):
        if supplied is None:
            continue
        if "date" in current[key]:
            patch[key] = {"date": value.date().isoformat()}
        else:
            patch[key] = {"dateTime": value.isoformat(),
                          "timeZone": current[key].get("timeZone") or TIMEZONE}
    # recurrence, attendees, reminders and all other fields remain in Google.
    try:
        updated = service.google_client.patch_event(calendar_id, current["id"], patch, current["etag"])
    except HttpError as exc:
        if exc.resp.status == 412:
            raise HTTPException(409, "Событие изменили в Google Calendar. Откройте форму заново.") from None
        raise

    if scope == "single":
        # Use Google's response, not submitted values, as the cache contents.
        row.title = updated.get("summary", "")
        row.description = updated.get("description", "")
        row.location = updated.get("location", "")
        row.start_time = service._parse_dt(updated["start"])
        row.end_time = service._parse_dt(updated["end"])
        row.last_synced = datetime.utcnow()
        service.db.commit()
        return {"id": row.id, "scope": scope, "synced": True,
                "title": row.title, "google_event_id": row.google_event_id,
                "start_time": row.start_time.isoformat(), "end_time": row.end_time.isoformat()}

    # Refresh all cached history too, not just the default 365-day window.
    # A moved series can change instance IDs. The ordinary full-snapshot sync
    # cancels obsolete rows/polls without moving their frozen vote dates.
    try:
        dates = [value for value, in service.db.query(CalendarEvent.start_time) if value]
        now = local_now()
        days = max(90, max(((value - now).days + 2 for value in dates), default=90))
        past_days = max(365, max(((now - value).days + 2 for value in dates), default=365))
        events = service.google_client.get_events(calendar_id, days=days, past_days=past_days)
        service.sync_from_google(events)
    except Exception:
        service.db.rollback()
        logger.exception("Series saved in Google; local refresh deferred to calendar sync")
        return {"id": event_id, "scope": scope, "synced": False,
                "warning": "Серия сохранена в Google Calendar. Расписание в приложении обновится после синхронизации."}
    return {"id": event_id, "scope": scope, "synced": True}
