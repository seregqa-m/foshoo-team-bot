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
