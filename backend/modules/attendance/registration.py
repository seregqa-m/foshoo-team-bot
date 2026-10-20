"""Register only identified voters of our polls in currently connected groups."""
import asyncio
import logging
from datetime import datetime, timedelta

from .models import VoterRegistration, ChatParticipant
from .services import answer_lock

logger = logging.getLogger(__name__)


def _set_registration_status(db, voter, chat_id, status):
    from modules.theater.models import TheaterShow
    if not voter or voter.telegram_chat_id != chat_id:
        return
    voter.membership_status = status
    if status != 'member':
        other = db.query(ChatParticipant).filter(
            ChatParticipant.user_id == voter.user_id, ChatParticipant.chat_id != chat_id,
            ChatParticipant.status == 'member',
            ChatParticipant.chat_id.in_(db.query(TheaterShow.telegram_chat_id))).first()
        if other:
            voter.telegram_chat_id = other.chat_id
            voter.membership_status = 'member'


def remember_voter(db, user, chat_id, *, force_registration=True):
    from modules.theater.models import TheaterShow
    if not chat_id or getattr(user, 'is_bot', False):
        return
    if not db.query(TheaterShow).filter_by(telegram_chat_id=chat_id).first():
        return
    membership = db.get(ChatParticipant, (chat_id, user.id))
    if membership is None:
        db.add(ChatParticipant(chat_id=chat_id, user_id=user.id))
    else:
        membership.revision += 1
        membership.status = 'pending'
    username = (user.username or '').lower().lstrip('@') or None
    name = ' '.join(filter(None, (getattr(user, 'first_name', ''), getattr(user, 'last_name', '')))).strip()
    name = name or username or f'Участник {user.id}'
    voter = db.get(VoterRegistration, user.id)
    if voter is None:
        db.add(VoterRegistration(user_id=user.id, username=username, display_name=name,
                                 telegram_chat_id=chat_id))
    else:
        identity_changed = (voter.username, voter.display_name, voter.telegram_chat_id) != (username, name, chat_id)
        voter.username, voter.display_name, voter.telegram_chat_id = username, name, chat_id
        if identity_changed or voter.membership_status != 'member':
            voter.membership_status = 'pending'
        # Re-read the ID binding on the next vote, including manual actor renames.
        if identity_changed or force_registration:
            voter.revision += 1


def _pending(chat_ids=None, force=False):
    from core.database import SessionLocal
    from modules.theater.models import TheaterShow
    from sqlalchemy import or_
    with SessionLocal() as db:
        chats = [c for c, in db.query(TheaterShow.telegram_chat_id).distinct() if c and (chat_ids is None or c in chat_ids)]
        query = db.query(ChatParticipant).filter(ChatParticipant.chat_id.in_(chats))
        if not force:
            query = query.filter(or_(
                    ChatParticipant.status == 'pending', ChatParticipant.checked_at.is_(None),
                    ChatParticipant.checked_at < datetime.utcnow() - timedelta(minutes=5)))
        return [(v.user_id, v.chat_id, v.revision) for v in query.all()]


def _mark(user_id, chat_id, revision, status):
    from core.database import SessionLocal
    from modules.theater.models import TheaterShow
    with answer_lock, SessionLocal() as db:
        voter = db.get(VoterRegistration, user_id)
        membership = db.get(ChatParticipant, (chat_id, user_id))
        if not membership or membership.revision != revision:
            return False
        connected = db.query(TheaterShow).filter_by(telegram_chat_id=chat_id).first()
        membership.status = status if connected else 'disconnected'
        membership.checked_at = datetime.utcnow()
        membership.revision += 1
        _set_registration_status(db, voter, chat_id, membership.status)
        db.commit()
    from core.access import invalidate_member_access
    invalidate_member_access(user_id)
    return True


async def sync_voter_registrations(bot, *, chat_ids=None, force=False, strict=False):
    """Telegram outages leave registration pending; they never discard a vote."""
    semaphore = asyncio.Semaphore(4)
    failures = []
    async def check(user_id, chat_id, revision):
        try:
            async with semaphore:
                member = await asyncio.wait_for(bot.get_chat_member(chat_id, user_id), timeout=5)
            present = is_present(member)
            applied = await asyncio.to_thread(_mark, user_id, chat_id, revision, 'member' if present else 'left')
            if not applied:
                failures.append(chat_id)  # A concurrent event/edit needs a fresh check.
        except Exception:
            failures.append(chat_id)
            logger.warning('Voter membership check deferred user_id=%s chat_id=%s', user_id, chat_id)
    await asyncio.gather(*(check(*item) for item in await asyncio.to_thread(_pending, chat_ids, force)))
    if strict and failures:
        from fastapi import HTTPException
        raise HTTPException(503, 'Не удалось проверить состав группы. Повторите напоминание позже.')


def is_present(member):
    return member.status in ('creator', 'administrator', 'member') or (
        member.status == 'restricted' and member.is_member)


def membership_event(chat_id, user, member):
    """Telegram membership updates invalidate cached access immediately."""
    from core.database import SessionLocal
    with answer_lock, SessionLocal() as db:
        if is_present(member) and not user.is_bot:
            remember_voter(db, user, chat_id, force_registration=False)
        db.flush()
        row = db.get(ChatParticipant, (chat_id, user.id))
        if not row:
            return
        row.status = 'member' if is_present(member) and not user.is_bot else 'left'
        row.revision += 1
        row.checked_at = datetime.utcnow()
        voter = db.get(VoterRegistration, user.id)
        _set_registration_status(db, voter, chat_id, row.status)
        db.commit()
    from core.access import invalidate_member_access
    invalidate_member_access(user.id)


def backfill_participants(db):
    """Recover known IDs from stored votes; never invent answers or full chat lists."""
    from types import SimpleNamespace
    from modules.polling.models import Poll, PollVote
    from modules.availability.models import AvailabilityPoll, AvailabilityVote
    candidates = [(v.user_id, v.username, v.telegram_chat_id) for v in db.query(VoterRegistration)]
    candidates += [(v.user_id, v.username, p.telegram_chat_id) for v, p in
                   db.query(PollVote, Poll).join(Poll, Poll.id == PollVote.poll_id)
                   if v.answer != 'retracted']
    candidates += [(v.user_id, v.username, p.telegram_chat_id) for v, p in
                   db.query(AvailabilityVote, AvailabilityPoll).join(
                       AvailabilityPoll, AvailabilityPoll.id == AvailabilityVote.poll_id)]
    for user_id, username, chat_id in candidates:
        if not chat_id or db.get(ChatParticipant, (chat_id, user_id)):
            continue
        old = db.get(VoterRegistration, user_id)
        user = SimpleNamespace(id=user_id, username=old.username if old else username,
                               first_name=old.display_name if old else '', last_name='', is_bot=False)
        remember_voter(db, user, chat_id)
        db.flush()
    db.commit()
