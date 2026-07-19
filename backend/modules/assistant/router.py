"""
FastAPI router для AI-ассистента.

Фаза 1: единственная ручка /chat принимает свободный текст,
проксирует в YandexGPT, возвращает ответ. Без tools, без confirm.
"""
from __future__ import annotations

import logging
import random
from typing import List, Optional

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
    "Запусти опрос на субботу",
    "Кто ещё не ответил на опрос занятости?",
    "Как записать доход от продажи билетов?",
    "Какие есть авто-опросы?",
    "Что умеет это приложение?",
    "Где посмотреть расписание?",
    "Как посмотреть свои траты?",
    "Как поменять состав спектакля?",
    "Что такое опрос занятости?",
    "Кто может создавать события?",
    "Как связаться с админом?",
]


class HistoryItem(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    user_id: int
    session_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[HistoryItem] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    session_id: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@router.get("/hints")
async def get_hints():
    """Случайные 4 подсказки из пула для chip-подсказок в UI."""
    hints = random.sample(HINTS_POOL, k=min(4, len(HINTS_POOL)))
    return {"hints": hints}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Один шаг диалога с ассистентом."""
    if not ASSISTANT_ENABLED:
        raise HTTPException(status_code=503, detail="Ассистент отключён")

    try:
        service = AssistantService(db)
    except LLMConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        result = await service.chat(
            user_id=request.user_id,
            message=request.message,
            history=[h.dict() for h in request.history],
        )
    except LLMConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except LLMProviderError as e:
        logger.error(f"LLM provider error: {e}")
        raise HTTPException(status_code=502, detail="Ошибка LLM. Попробуй ещё раз.")

    return ChatResponse(
        reply=result.text,
        session_id=request.session_id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
