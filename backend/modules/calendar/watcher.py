"""Deterministic title checks; durable baseline and per-superadmin delivery records."""
import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from html import escape

from modules.admin.models import SuperAdmin
from modules.theater.routing import show_aliases, match_show
from core.time import local_now
from .classification import BRACKETS, EVENT_TYPES, TYPE_WORD, classify_event
from .ical import event_url
from .models import CalendarEvent, CalendarWatchState, CalendarWatchDelivery

logger = logging.getLogger(__name__)


def naming_problem(title, aliases):
    title = title or ''
    if not title.strip():
        return 'У события нет названия. Укажите название и тип: «Название [Реп]» или «Название [Спект]». Для обычного события достаточно понятного названия.'
    explicit = set()
    for match in BRACKETS.finditer(title):
        raw = next(v for v in match.groups() if v is not None)
        key = ' '.join(raw.split()).casefold().rstrip('.')
        if key in EVENT_TYPES:
            explicit.add(EVENT_TYPES[key])
    explicit.update(EVENT_TYPES[m.group().casefold()] for m in TYPE_WORD.finditer(BRACKETS.sub(' ', title)))
    if len(explicit) > 1:
        return 'В названии одновременно указаны репетиция и спектакль. Оставьте один тип: «Название [Реп]» или «Название [Спект]».'
    show = match_show(title, aliases)
    kind = classify_event(title, aliases)['event_type']
    if not explicit and kind:
        name = show.name if show else 'Название'
        return f'Не указан явный тип. Для показа: «{name} [Спект]», для репетиции: «{name} [Реп]». Допустимы также слова «Спектакль» и «Репетиция».'
    if kind == 'rehearsal' and not show:
        return 'Не удалось однозначно определить спектакль. Укажите ровно одно название из «Спектакли и чаты»: «Название [Реп]». Проверьте опечатки или добавьте название/псевдоним в каталог.'
    return None


def pending_problems(db):
    aliases = show_aliases(db)
    events = db.query(CalendarEvent).filter(CalendarEvent.is_cancelled == False,
                                            CalendarEvent.end_time > local_now()).order_by(CalendarEvent.start_time).all()
    baseline = db.get(CalendarWatchState, 0) is None
    if baseline:
        db.add(CalendarWatchState(event_id=0, title='baseline'))
    pending = {}
    for event in events:
        state = db.get(CalendarWatchState, event.id)
        changed = state is None or state.title != (event.title or '')
        if state is None:
            state = CalendarWatchState(event_id=event.id, title=event.title or '')
            db.add(state)
        problem = naming_problem(event.title, aliases)
        if baseline or not problem:
            state.issue_key = None
        elif changed:
            # Repeated instances with the same malformed title need one message.
            identity = event.recurring_event_id or event.google_event_id or str(event.id)
            state.issue_key = hashlib.sha256(f'{identity}\0{event.title}\0{problem}'.encode()).hexdigest()
        state.title = event.title or ''
        if state.issue_key and problem:
            pending.setdefault(state.issue_key, (event, problem))
    db.commit()
    return pending


async def check_calendar_names(db, bot):
    pending = pending_problems(db)
    recipients = [row.telegram_user_id for row in db.query(SuperAdmin).all()]
    sent = 0
    attempts = 0
    for issue, (event, problem) in pending.items():
        url = event_url(event)
        text = ('⚠️ Проверьте название события\n\n'
                f'<b>{escape((event.title or "Без названия")[:500])}</b>\n'
                f'{event.start_time:%d.%m.%Y %H:%M}\n\n{escape(problem[:1500])}')
        if event.recurring_event_id:
            text += '\n\nЭто повторяющееся событие. Если ошибка во всей серии, исправьте название всей серии.'
        if url:
            text += f'\n\n<a href="{escape(url, quote=True)}">Открыть событие в Google Calendar</a>'
        for uid in recipients:
            delivery = db.get(CalendarWatchDelivery, (issue, uid))
            now = datetime.utcnow()
            if delivery and (delivery.sent_at or (delivery.retry_after and delivery.retry_after > now)):
                continue
            if attempts >= 20:
                return sent
            # Recheck revocations between sends.
            if not db.get(SuperAdmin, uid, populate_existing=True):
                continue
            if not delivery:
                delivery = CalendarWatchDelivery(issue_key=issue, recipient_id=uid)
                db.add(delivery)
            # A crash/timeout must not turn every sync into a message storm.
            delivery.retry_after = now + timedelta(hours=1)
            db.commit()
            attempts += 1
            try:
                await asyncio.wait_for(bot.send_message(uid, text, parse_mode='HTML',
                                                        disable_web_page_preview=True), timeout=15)
            except Exception:
                logger.warning('Calendar title notification deferred recipient=%s event=%s', uid, event.id)
            else:
                delivery.sent_at = datetime.utcnow()
                delivery.retry_after = None
                db.commit()
                sent += 1
    return sent
