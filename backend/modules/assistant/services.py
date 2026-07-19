"""
AssistantService — оркестратор одного chat-запроса.

Фаза 1: без tools, без guardrails — просто чистый разговор с YandexGPT.
Дальнейшие фазы добавят: build_context, function calling, action_token + confirm.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .llm_client import ChatMessage, LLMClient, LLMResponse, get_llm_client

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_BASE = """Ты — помощник актёрам театр-студии «FoShoo».
Отвечай кратко, по-русски, дружелюбно.
Ты пока работаешь в базовом режиме: можешь только отвечать на вопросы,
без действий в приложении. Действия (создать событие, добавить расход,
запустить опрос) будут доступны в следующих обновлениях.
"""


class AssistantService:
    def __init__(self, db: Session, llm: LLMClient | None = None):
        self.db = db
        self.llm = llm or get_llm_client()

    async def chat(
        self,
        *,
        user_id: int,
        message: str,
        history: list[dict] | None = None,
    ) -> LLMResponse:
        """Обработать одну реплику пользователя."""
        messages: list[ChatMessage] = [ChatMessage(role="system", text=SYSTEM_PROMPT_BASE)]
        for h in history or []:
            role = h.get("role")
            text = h.get("content", "")
            if role in ("user", "assistant") and text:
                messages.append(ChatMessage(role=role, text=text))
        messages.append(ChatMessage(role="user", text=message))

        response = await self.llm.chat(messages)
        return response
