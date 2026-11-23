"""Superadmins may record common day answers for verified group members."""
import asyncio
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.time import local_now
from modules.admin.models import AppUser, SuperAdmin
from modules.admin.router import require_superadmin
from modules.theater.models import TheaterShow
from .models import ChatParticipant, DayAnswer, VoterRegistration
from .registration import is_present, remember_voter
from .router import _day_data, month_answers
from .services import answer_lock, record_answers

router = APIRouter(prefix='/api/attendance/participants', tags=['attendance'],
                   dependencies=[Depends(require_superadmin)])


def connected_chats(db):
    return [chat for chat, in db.query(TheaterShow.telegram_chat_id).distinct() if chat]


async def verified_member(target_id, chats, semaphore):
    from bot import bot
    failed = False
    for chat_id in chats:
        try:
            async with semaphore:
                member = await asyncio.wait_for(bot.get_chat_member(chat_id, target_id), timeout=4)
            if is_present(member) and not member.user.is_bot:
                return chat_id, member.user
        except Exception:
            failed = True
    if failed:
        raise HTTPException(503, 'Не удалось проверить участника в Telegram. Попробуйте ещё раз.')
    raise HTTPException(403, 'Участник больше не состоит в подключённых группах')


@router.get('')
async def participants(db: Session = Depends(get_db)):
    # Bot API cannot enumerate a group. Include identities from app logins as
    # well as polls/membership events so non-voters and other superadmins appear.
    ids = {uid for uid, in db.query(AppUser.telegram_user_id)}
    ids.update(uid for uid, in db.query(VoterRegistration.user_id))
    ids.update(uid for uid, in db.query(ChatParticipant.user_id).distinct())
    ids.update(uid for uid, in db.query(SuperAdmin.telegram_user_id))
    chats, semaphore = connected_chats(db), asyncio.Semaphore(4)
    ids = sorted(ids)
    results = await asyncio.gather(*(verified_member(uid, chats, semaphore) for uid in ids),
                                   return_exceptions=True)
    people, incomplete = [], False
    for uid, result in zip(ids, results):
        if isinstance(result, Exception):
            incomplete |= not isinstance(result, HTTPException) or result.status_code != 403
            continue
        _, user = result
        voter = db.get(VoterRegistration, uid)
        people.append({'telegram_user_id': uid,
                       'name': (voter.actor_name if voter else None) or user.full_name,
                       'username': user.username or ''})
    people.sort(key=lambda person: (person['name'].casefold(), person['telegram_user_id']))
    return {'participants': people, 'incomplete': incomplete}


@router.get('/{target_id}')
async def participant_answers(target_id: int, month: str | None = None,
                              db: Session = Depends(get_db)):
    await verified_member(target_id, connected_chats(db), asyncio.Semaphore(1))
    return {**month_answers(db, target_id, month), 'today': local_now().date().isoformat(),
            'can_create': True}


class DelegatedAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    date: date
    answer: Literal['yes', 'no', 'unknown']
    expected_revision: int = Field(strict=True, ge=0)


@router.put('/{target_id}')
async def change_participant_answer(target_id: int, payload: DelegatedAnswer,
                                    request: Request, db: Session = Depends(get_db)):
    today = local_now().date()
    if payload.date < today:
        raise HTTPException(422, 'Ответы за прошедшие дни изменить нельзя')
    chat_id, target = await verified_member(target_id, connected_chats(db), asyncio.Semaphore(1))
    actor_id = request.state.telegram_user.id
    with answer_lock:
        db.expire_all()
        # Recheck after the Telegram await, including role revocation/chat removal.
        require_superadmin(request, db)
        if chat_id not in connected_chats(db):
            raise HTTPException(409, 'Список групп изменился. Обновите страницу.')
        row = db.get(DayAnswer, (target_id, payload.date))
        source = f'app-admin:{actor_id}:{payload.date.isoformat()}:{payload.expected_revision}'
        if (row and row.revision == payload.expected_revision + 1
                and row.source == source and row.answer == payload.answer):
            return _day_data(row, today)
        if (row.revision if row else 0) != payload.expected_revision:
            raise HTTPException(409, 'Ответ уже изменился. Проверьте актуальное значение и повторите выбор.')
        if row is None or row.answer != payload.answer:
            remember_voter(db, target, chat_id, force_registration=False)
            db.flush()
            membership = db.get(ChatParticipant, (chat_id, target_id))
            membership.status, membership.checked_at = 'member', datetime.utcnow()
            voter = db.get(VoterRegistration, target_id)
            voter.membership_status = 'member'
            record_answers(db, target_id, target.username, source, {payload.date: payload.answer})
            row = db.get(DayAnswer, (target_id, payload.date))
            row.actor_name = voter.actor_name or row.actor_name
            db.commit()
        return _day_data(row, today)
