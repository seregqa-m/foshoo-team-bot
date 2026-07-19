"""
FastAPI router для AI-ассистента.

Фаза 4: /chat может вернуть pending_action с action_token; /execute проверяет
токен и вызывает handler. /hints — набор ротирующихся chip-подсказок.
"""
from __future__ import annotations

import logging
import random
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import ASSISTANT_ENABLED
from core.database import get_db

from .llm_client import LLMConfigurationError, LLMProviderError
from .services import AssistantService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


HINTS_POOL = [
    "Что у нас с копилкой?",
    "Когда следующее занятие?",
    "Кто в составе спектакля?",
    "Вчера потратил 500 на реквизит",
    "Добавь 3000 на костюмы для Урода",
    "Перенеси репетицию с воскресенья на пятницу 20:00",
    "Добавь занятие в субботу 19:00-22:00 для труппы 1",
    "Кто ещё не ответил на опрос занятости?",
    "Как записать доход от продажи билетов?",
    "Какие сейчас настройки авто-опросов?",
    "Что умеет это приложение?",
    "Где посмотреть расписание?",
    "Как посмотреть свои траты?",
    "Как поменять состав спектакля?",
    "Что такое опрос занятости?",
]


class HistoryItem(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    user_id: int
    username: str = ""
    session_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[HistoryItem] = Field(default_factory=list)


class PendingActionOut(BaseModel):
    action_token: str
    tool_name: str
    preview: dict[str, Any]


class ChatResponse(BaseModel):
    reply: str
    session_id: Optional[str] = None
    pending_action: Optional[PendingActionOut] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class ExecuteRequest(BaseModel):
    user_id: int
    action_token: str


class ExecuteResponse(BaseModel):
    success: bool
    result: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


@router.get("/hints")
async def get_hints():
    return {"hints": random.sample(HINTS_POOL, k=min(4, len(HINTS_POOL)))}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    if not ASSISTANT_ENABLED:
        raise HTTPException(status_code=503, detail="Ассистент отключён")

    try:
        service = AssistantService(db)
    except LLMConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        result = await service.chat(
            user_id=request.user_id,
            username=request.username or "",
            message=request.message,
            history=[h.dict() for h in request.history],
        )
    except LLMConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except LLMProviderError as e:
        logger.error(f"LLM provider error: {e}")
        raise HTTPException(status_code=502, detail="Ошибка LLM. Попробуй ещё раз.")

    pending = None
    if result.pending_action:
        pending = PendingActionOut(
            action_token=result.pending_action.action_token,
            tool_name=result.pending_action.tool_name,
            preview=result.pending_action.preview,
        )
    return ChatResponse(
        reply=result.reply,
        session_id=request.session_id,
        pending_action=pending,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


@router.post("/execute", response_model=ExecuteResponse)
async def execute(request: ExecuteRequest, db: Session = Depends(get_db)):
    """Выполнить отложенное действие по action_token, полученному от /chat."""
    if not ASSISTANT_ENABLED:
        raise HTTPException(status_code=503, detail="Ассистент отключён")

    service = AssistantService(db)
    try:
        result = await service.execute_pending(user_id=request.user_id, action_token=request.action_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"execute failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    return ExecuteResponse(success=bool(result.get("success")), result=result.get("result") or {}, message="Готово")
