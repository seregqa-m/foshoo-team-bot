import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from modules.admin.router import require_superadmin
from .models import TheaterAudit, TheaterChat, TheaterShow
from .services import import_shows, inspect_chat, register_chat, set_show

router = APIRouter(prefix='/api/admin/theater', tags=['theater'],
                   dependencies=[Depends(require_superadmin)])


def show_data(show):
    return {'id': show.id, 'name': show.name, 'telegram_chat_id': show.telegram_chat_id,
            'revision': show.revision}


@router.get('')
def catalog(db: Session = Depends(get_db)):
    return {
        'shows': [show_data(show) for show in db.query(TheaterShow).order_by(TheaterShow.name).all()],
        'chats': [{'telegram_chat_id': chat.telegram_chat_id, 'title': chat.title,
                   'checked_at': chat.checked_at.isoformat() + 'Z'}
                  for chat in db.query(TheaterChat).order_by(TheaterChat.title).all()],
        'audit': [{'id': row.id, 'actor_id': row.actor_id, 'action': row.action,
                   'details': json.loads(row.details), 'created_at': row.created_at.isoformat() + 'Z'}
                  for row in db.query(TheaterAudit).order_by(TheaterAudit.id.desc()).limit(30).all()],
    }


class ChatRequest(BaseModel):
    telegram_chat_id: int = Field(strict=True, lt=0, ge=-(2**52 - 1))


@router.post('/chats')
async def add_chat(req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    from bot import bot
    title = await inspect_chat(bot, req.telegram_chat_id)
    register_chat(db, request.state.telegram_user.id, req.telegram_chat_id, title)
    return {'status': 'registered', 'title': title}


class ShowRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post('/shows')
def add_show(req: ShowRequest, request: Request, db: Session = Depends(get_db)):
    added = import_shows(db, request.state.telegram_user.id, [req.name])
    return {'added': added}


def read_sheet_names():
    from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    from sheets_client import SheetsClient
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        raise HTTPException(503, 'Google Sheets не настроен')
    try:
        return SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID, timeout=5).get_show_names()
    except Exception:
        raise HTTPException(502, 'Не удалось прочитать спектакли из Google Sheets') from None


@router.post('/shows/import')
async def import_catalog(request: Request, db: Session = Depends(get_db)):
    try:
        names = await asyncio.wait_for(asyncio.to_thread(read_sheet_names), timeout=10)
    except asyncio.TimeoutError:
        raise HTTPException(504, 'Таблица не ответила вовремя. Попробуйте ещё раз.') from None
    return {'added': import_shows(db, request.state.telegram_user.id, names)}


class UpdateShowRequest(ShowRequest):
    telegram_chat_id: int | None = Field(..., strict=True, lt=0, ge=-(2**52 - 1))
    expected_revision: int = Field(strict=True, ge=0)


@router.put('/shows/{show_id}')
async def update_show(show_id: int, req: UpdateShowRequest, request: Request,
                      db: Session = Depends(get_db)):
    title = None
    if req.telegram_chat_id is not None:
        from bot import bot
        title = await inspect_chat(bot, req.telegram_chat_id)
    show = set_show(db, request.state.telegram_user.id, show_id, req.name,
                    req.telegram_chat_id, req.expected_revision, verified_chat_title=title)
    return show_data(show)
