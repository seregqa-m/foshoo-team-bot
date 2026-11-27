"""Explicit preview → send of one selected schedule to a verified Telegram group."""
import asyncio
import json
from datetime import date, datetime, timedelta
from threading import RLock

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile
from babel.dates import format_date
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from config import GROUP_CHAT_ID
from core.database import get_db
from core.time import local_now, as_local
from modules.theater.models import TheaterChat, TheaterShow
from modules.theater.routing import poll_link
from .models import RepertoireShare
from .repertoire import RepertoireProblem, digest
from .repertoire_source import get_rules
from .repertoire_search import search_key, cached_variant

router = APIRouter()
_preview_lock = RLock()


def get_bot():
    from bot import bot
    return bot


def destinations(db):
    ids = {chat for chat, in db.query(TheaterShow.telegram_chat_id).distinct() if chat}
    if GROUP_CHAT_ID:
        ids.add(int(GROUP_CHAT_ID))
    titles = {c.telegram_chat_id: c.title for c in db.query(TheaterChat).all()}
    return {chat: titles.get(chat, 'Общий чат' if chat == GROUP_CHAT_ID else str(chat)) for chat in sorted(ids)}


async def checked_chat(bot, db, chat_id, request):
    if chat_id not in destinations(db):
        raise HTTPException(403, 'Выберите подключённый чат')
    try:
        if not getattr(request.state, 'is_superadmin', False):
            member = await asyncio.wait_for(bot.get_chat_member(chat_id, request.state.telegram_user.id), 5)
            if member.status not in ('creator', 'administrator'):
                raise HTTPException(403, 'Отправить план может администратор этого чата')
        chat = await asyncio.wait_for(bot.get_chat(chat_id), 5)
        if chat.type not in ('group', 'supergroup'):
            raise HTTPException(403, 'Для согласования выберите группу')
        return {'id': chat_id, 'title': chat.title or str(chat_id)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Не удалось проверить доступ к чату. Повторите позже.') from None


@router.get('/repertoire/chats')
async def share_chats(request: Request, db: Session = Depends(get_db)):
    bot = get_bot()
    chats, failed = [], False
    for chat_id in destinations(db):
        try:
            chats.append(await checked_chat(bot, db, chat_id, request))
        except HTTPException as exc:
            failed |= exc.status_code == 503
    return {'chats': chats, 'warning': 'Не все чаты удалось проверить. Закройте и откройте отправку для повторной проверки.' if failed else None}


def message_text(month, variant, target, warnings):
    label = format_date(date.fromisoformat(month + '-01'), 'LLLL yyyy', locale='ru_RU')
    lines = [f'План афиши на согласование — {label}', '', f'Подобрано {variant["count"]} из {target} показов.', '']
    for entry in sorted(variant['entries'], key=lambda e: (e['date'], e['name'])):
        day = format_date(date.fromisoformat(entry['date']), 'd MMM, EEE', locale='ru_RU')
        suffix = ' (уже в расписании)' if entry['fixed'] else ' (репетиционный слот)' if entry.get('rehearsals') else ''
        clock = f' в {as_local(datetime.fromisoformat(entry["start_time"])):%H:%M}' if entry.get('start_time') else ''
        lines.append(f'{day}{clock} — {entry["name"]}{suffix}')
    if variant['missing']:
        lines += ['', 'Не хватает: ' + '; '.join(f'{s["name"]} — {s["count"]}' for s in variant['missing']) + '.']
    if variant.get('manual'):
        lines.append('Вариант с ручными заменами.')
    if variant.get('excess'):
        lines.append('Сверх плана: ' + '; '.join(f'{s["name"]} — {s["count"]}' for s in variant['excess']) + '.')
    for warning in variant['spread_warnings']:
        lines.append(f'Разнос: {warning["name"]}, {" / ".join(warning["dates"])} — {warning["gap"]} дн., желательно {warning["desired"]}.')
    for warning in variant['load_warnings']:
        lines.append(f'Нагрузка: {warning["actor"]} — {len(warning["dates"])} дня подряд ({", ".join(warning["dates"])}).')
    if warnings:
        lines += ['', 'Проверить перед утверждением:', *[f'• {w}' for w in warnings]]
    lines += ['', 'Предлагаемый вариант для финального согласования. Просьба подтвердить даты или написать замечания в чат.',
              'Новые показы ещё не назначены; репетиции автоматически не изменены.']
    return '\n'.join(lines)


def rules_signature(rules, revision):
    return digest([rules.model_dump(mode='json'), revision])


def share_data(row):
    payload = json.loads(row.payload)
    return {'id': row.id, 'status': row.status, 'chat_id': row.chat_id, 'chat_title': payload['chat_title'],
            'text': payload['text'], 'delivery': payload['delivery'], 'error': row.error,
            'link': poll_link(row.chat_id, row.message_id), 'expires_at': row.expires_at.isoformat() + 'Z'}


class PreviewRequest(BaseModel):
    month: str
    search_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    variant_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    chat_id: int = Field(strict=True, lt=0, ge=-(2**52 - 1))
    expected_fingerprint: str
    expected_revision: int = Field(ge=0)


def prepare_preview(req, actor_id, title, db):
    from .repertoire_router import valid_month, snapshot
    valid_month(req.month)
    source = snapshot(db, req.month, fresh=True)
    rules, revision, _ = get_rules(db, req.month, source['shows'])
    problem = RepertoireProblem(source, rules, local_now().date())
    if source['fingerprint'] != req.expected_fingerprint or revision != req.expected_revision or search_key(problem) != req.search_id:
        raise HTTPException(409, 'План изменился. Обновите предложения и выберите вариант заново.')
    variant = cached_variant(req.search_id, req.variant_id)
    if not variant or not variant['entries']:
        raise HTTPException(409, 'Вариант больше не доступен. Обновите предложения.')
    text = message_text(req.month, variant, problem.target, source['warnings'])
    key = digest([actor_id, req.chat_id, text])
    payload = {'text': text, 'chat_title': title, 'fingerprint': source['fingerprint'],
               'rules_signature': rules_signature(rules, revision), 'day': local_now().date().isoformat(),
               'delivery': 'document' if len(text.encode('utf-16-le')) // 2 > 3500 else 'message'}
    with _preview_lock:
        row = db.get(RepertoireShare, key, populate_existing=True)
        if row and row.status in ('sending', 'unknown', 'sent'):
            return share_data(row)
        if row is None:
            row = RepertoireShare(id=key, actor_id=actor_id, chat_id=req.chat_id, month=req.month, status='preview')
            db.add(row)
        row.payload = json.dumps(payload, ensure_ascii=False)
        row.expires_at = datetime.utcnow() + timedelta(minutes=15)
        db.commit()
        return share_data(row)


@router.post('/repertoire/share/preview')
async def preview_share(req: PreviewRequest, request: Request, db: Session = Depends(get_db)):
    chat = await checked_chat(get_bot(), db, req.chat_id, request)
    return await run_in_threadpool(prepare_preview, req, request.state.telegram_user.id, chat['title'], db)


class SendRequest(BaseModel):
    preview_id: str = Field(pattern=r'^[a-f0-9]{64}$')


def check_fresh(row, db):
    from .repertoire_router import snapshot
    payload = json.loads(row.payload)
    if row.expires_at < datetime.utcnow() or payload['day'] != local_now().date().isoformat():
        raise HTTPException(409, 'Предпросмотр устарел. Подготовьте сообщение заново.')
    source = snapshot(db, row.month, fresh=True)
    rules, revision, _ = get_rules(db, row.month, source['shows'])
    if source['fingerprint'] != payload['fingerprint'] or rules_signature(rules, revision) != payload['rules_signature']:
        raise HTTPException(409, 'Ответы, календарь или параметры изменились. Обновите план и предпросмотр перед отправкой.')


@router.post('/repertoire/share/send')
async def send_share(req: SendRequest, request: Request, db: Session = Depends(get_db)):
    row = db.get(RepertoireShare, req.preview_id, populate_existing=True)
    if not row or row.actor_id != request.state.telegram_user.id:
        raise HTTPException(404, 'Предпросмотр не найден')
    bot = get_bot()
    await checked_chat(bot, db, row.chat_id, request)
    if row.status in ('sent', 'sending', 'unknown'):
        return share_data(row)
    if row.retry_after and row.retry_after > datetime.utcnow():
        raise HTTPException(429, 'Telegram просит подождать перед повторной отправкой.')
    await run_in_threadpool(check_fresh, row, db)
    claimed = db.execute(update(RepertoireShare).where(RepertoireShare.id == row.id,
        RepertoireShare.status.in_(['preview', 'failed'])).values(status='sending', error=None)).rowcount
    db.commit()
    db.refresh(row)
    if not claimed:
        return share_data(row)
    payload = json.loads(row.payload)
    try:
        if payload['delivery'] == 'document':
            result = await bot.send_document(chat_id=row.chat_id,
                document=BufferedInputFile(payload['text'].encode('utf-8'), filename=f'plan-{row.month}.txt'),
                caption='План афиши на финальное согласование', parse_mode=None)
        else:
            result = await bot.send_message(chat_id=row.chat_id, text=payload['text'], parse_mode=None)
    except TelegramRetryAfter as exc:
        row.status = 'failed'
        row.retry_after = datetime.utcnow() + timedelta(seconds=exc.retry_after)
        row.error = f'Telegram просит подождать {exc.retry_after} сек.'
    except (TelegramBadRequest, TelegramForbiddenError):
        row.status = 'failed'
        row.error = 'Telegram отклонил отправку. Проверьте доступ бота к чату и право отправки сообщений.'
    except Exception:
        row.status = 'unknown'
        row.error = 'Доставка не подтверждена. Проверьте чат; автоматического повтора не будет.'
    else:
        row.status, row.message_id = 'sent', result.message_id
    db.commit()
    return share_data(row)
