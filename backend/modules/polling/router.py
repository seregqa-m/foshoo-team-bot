"""
FastAPI router для опросов
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from .services import PollingService


class CreatePollRequest(BaseModel):
    title: str
    description: str = None
    expires_in_hours: int = 24
    calendar_event_id: int = None


class VoteRequest(BaseModel):
    answer: str  # "yes", "no", "maybe"


router = APIRouter(prefix="/api/polls", tags=["polls"])


@router.get("/events-summary")
async def get_events_poll_summary(db: Session = Depends(get_db)):
    """Последний опрос для каждого события: attending/not_attending counts."""
    from .models import Poll, PollVote
    polls = db.query(Poll).filter(Poll.calendar_event_id.isnot(None)).order_by(Poll.created_at.desc()).all()
    seen = set()
    summary = {}
    for poll in polls:
        eid = poll.calendar_event_id
        if eid in seen:
            continue
        seen.add(eid)
        votes = db.query(PollVote).filter(PollVote.poll_id == poll.id).all()
        tg_link = None
        if poll.telegram_message_id:
            from config import GROUP_CHAT_ID
            if GROUP_CHAT_ID:
                cid = str(abs(GROUP_CHAT_ID))
                if cid.startswith('100'):
                    cid = cid[3:]
                tg_link = f"https://t.me/c/{cid}/{poll.telegram_message_id}"
        summary[str(eid)] = {
            "poll_id": poll.id,
            "attending": sum(1 for v in votes if v.answer == "yes"),
            "not_attending": sum(1 for v in votes if v.answer == "no"),
            "telegram_message_id": poll.telegram_message_id,
            "created_at": poll.created_at.isoformat() if poll.created_at else None,
            "tg_link": tg_link,
        }
    return {"summary": summary}


@router.get("/all")
async def get_all_polls(db: Session = Depends(get_db)):
    """Все опросы с результатами голосования"""
    service = PollingService(db)
    return {"polls": service.get_all_polls_with_results()}


@router.get("/")
async def get_active_polls(db: Session = Depends(get_db)):
    """Получить активные опросы"""
    service = PollingService(db)
    polls = service.get_active_polls()

    return {
        "polls": [
            {
                "id": p.id,
                "title": p.title,
                "description": p.description,
                "expires_at": p.expires_at.isoformat()
            }
            for p in polls
        ]
    }


@router.post("/create")
async def create_poll(
    request: CreatePollRequest,
    user_id: int = None,
    db: Session = Depends(get_db)
):
    """Создать новый опрос"""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    service = PollingService(db)
    poll = service.create_poll(
        title=request.title,
        description=request.description,
        created_by=user_id,
        expires_in_hours=request.expires_in_hours,
        calendar_event_id=request.calendar_event_id
    )

    return {"poll_id": poll.id, "title": poll.title}


@router.get("/{poll_id}")
async def get_poll_results(poll_id: int, db: Session = Depends(get_db)):
    """Получить результаты опроса"""
    service = PollingService(db)
    results = service.get_poll_results(poll_id)

    if not results:
        raise HTTPException(status_code=404, detail="Poll not found")

    return results


@router.post("/{poll_id}/stop")
async def stop_poll(poll_id: int, db: Session = Depends(get_db)):
    """Остановить опрос: закрыть в Telegram и пометить неактивным в БД."""
    from bot import bot
    from config import GROUP_CHAT_ID
    service = PollingService(db)
    poll = service.get_poll(poll_id)
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    if poll.telegram_message_id and GROUP_CHAT_ID:
        try:
            await bot.stop_poll(chat_id=GROUP_CHAT_ID, message_id=poll.telegram_message_id)
        except Exception as e:
            logger.warning(f"stop_poll telegram failed: {e}")
    poll.is_active = False
    db.commit()
    return {"status": "stopped"}


@router.post("/{poll_id}/pin")
async def pin_poll(poll_id: int, db: Session = Depends(get_db)):
    """Закрепить сообщение с опросом в группе."""
    from bot import bot
    from config import GROUP_CHAT_ID
    service = PollingService(db)
    poll = service.get_poll(poll_id)
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    if not poll.telegram_message_id or not GROUP_CHAT_ID:
        raise HTTPException(status_code=400, detail="Нет Telegram message_id или GROUP_CHAT_ID")
    try:
        await bot.pin_chat_message(chat_id=GROUP_CHAT_ID, message_id=poll.telegram_message_id, disable_notification=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "pinned"}


@router.delete("/{poll_id}")
async def delete_poll(poll_id: int, force: bool = False, db: Session = Depends(get_db)):
    """Удалить опрос и все голоса из БД. Если есть голоса — требует ?force=true."""
    from .models import PollVote
    service = PollingService(db)
    poll = service.get_poll(poll_id)
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    vote_count = db.query(PollVote).filter(PollVote.poll_id == poll_id).count()
    if vote_count > 0 and not force:
        raise HTTPException(
            status_code=409,
            detail=f"Опрос содержит {vote_count} голосов. Для удаления передайте ?force=true"
        )
    db.delete(poll)
    db.commit()
    return {"status": "deleted"}


@router.post("/{poll_id}/vote")
async def vote(
    poll_id: int,
    request: VoteRequest,
    user_id: int = None,
    db: Session = Depends(get_db)
):
    """Проголосовать в опросе"""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    service = PollingService(db)
    vote_result = service.vote(poll_id, user_id, request.answer)

    return {"status": "voted", "answer": vote_result.answer}
