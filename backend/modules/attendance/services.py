import json
import logging
import os
from datetime import datetime
from threading import RLock

from .models import AnswerHistory, AnswerSource, DayAnswer, PollUpdate

logger = logging.getLogger(__name__)
answer_lock = RLock()


def record_answers(db, user_id, username, source, answers):
    """Caller commits publication state and answers together under answer_lock."""
    payload = json.dumps({day.isoformat(): answer for day, answer in sorted(answers.items())})
    previous = db.get(AnswerSource, (source, user_id))
    if previous and previous.payload == payload:
        return
    old_answers = json.loads(previous.payload) if previous else {}
    if previous:
        previous.payload = payload
    else:
        db.add(AnswerSource(source=source, user_id=user_id, payload=payload))
    for day, answer in answers.items():
        if old_answers.get(day.isoformat()) == answer:
            continue
        row = db.get(DayAnswer, (user_id, day))
        # Retracting an older publication must not erase a newer answer elsewhere.
        if answer == 'retracted' and row and row.source != source:
            continue
        if row is None:
            row = DayAnswer(user_id=user_id, day=day, revision=0)
            db.add(row)
        row.username = (username or row.username or '').lower().lstrip('@') or None
        row.answer, row.source = answer, source
        row.revision += 1
        row.updated_at = datetime.utcnow()
        db.add(AnswerHistory(user_id=user_id, day=day, answer=answer, source=source))


def accept_update(db, update_id):
    if update_id is None:
        return True
    if db.get(PollUpdate, update_id):
        return False
    db.add(PollUpdate(update_id=update_id))
    return True


def option_day(option, db):
    if option.selected_date:
        return option.selected_date
    from modules.calendar.models import CalendarEvent
    event = db.get(CalendarEvent, option.calendar_event_id) if option.calendar_event_id else None
    return event.start_time.date() if event and event.start_time else None


def answered_usernames(db, day):
    """Latest common answer wins; fall back only for unmigratable legacy votes."""
    from modules.polling.models import Poll, PollVote
    from modules.availability.models import AvailabilityPollOption, AvailabilityVote
    from modules.calendar.models import CalendarEvent
    rows = db.query(DayAnswer).filter_by(day=day).all()
    known_ids = {r.user_id for r in rows}
    result = {r.username for r in rows if r.username and r.answer != 'retracted'}
    for vote, poll in db.query(PollVote, Poll).join(Poll, Poll.id == PollVote.poll_id).all():
        event = db.get(CalendarEvent, poll.calendar_event_id) if poll.calendar_event_id else None
        poll_day = poll.selected_date or (event.start_time.date() if event and event.start_time else None)
        if poll_day == day and vote.user_id not in known_ids and vote.username:
            result.add(vote.username.lower())
    for vote, option in db.query(AvailabilityVote, AvailabilityPollOption).join(
            AvailabilityPollOption, AvailabilityPollOption.poll_id == AvailabilityVote.poll_id).all():
        if vote.user_id not in known_ids and vote.username and option_day(option, db) == day:
            result.add(vote.username.lower())
    return result


def export_pending(db):
    """Retry current values, never queued obsolete values. Keep role cells intact."""
    from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        return
    from sheets_client import SheetsClient
    with answer_lock:
        pending = db.query(DayAnswer).filter(DayAnswer.exported_revision < DayAnswer.revision).all()
        if not pending:
            return
        try:
            client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID, timeout=5)
            mapping = client.get_actor_mapping()
            for row in pending:
                if not row.username:
                    continue
                actor_name = mapping.get(row.username)
                if isinstance(actor_name, str) and actor_name:
                    row.actor_name = actor_name
                if client.record_poll_answer(row.username, datetime.combine(row.day, datetime.min.time()), row.answer, actor_name=row.actor_name):
                    row.exported_revision = row.revision
            db.commit()
        except Exception:
            db.rollback()
            logger.exception('Shared attendance export will be retried')


def planning_answers(db, month, client):
    """The planner uses the ledger immediately, even while Sheets export is pending."""
    from datetime import date
    from calendar import monthrange
    first = date.fromisoformat(month + '-01')
    last = first.replace(day=monthrange(first.year, first.month)[1])
    rows = db.query(DayAnswer).filter(DayAnswer.day >= first, DayAnswer.day <= last).all()
    if not rows:
        return {}
    mapping = client.get_actor_mapping()
    result = {}
    for row in rows:
        actor = row.actor_name or mapping.get(row.username)
        if isinstance(actor, str) and actor:
            result.setdefault(row.day.isoformat(), {})[' '.join(actor.split()).casefold()] = row.answer
    return result
