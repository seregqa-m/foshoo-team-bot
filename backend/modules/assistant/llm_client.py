"""
Провайдер-агностичная обёртка для LLM.

MVP-реализация — YandexGPT через Yandex Cloud Foundation Models REST API.
Дизайн позволяет позже подменить провайдера (OpenAI-совместимый API,
Claude через посредника, OSS-модели) без изменения вызывающего кода.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from config import YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_GPT_MODEL

logger = logging.getLogger(__name__)

YANDEX_COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


class LLMConfigurationError(RuntimeError):
    """Не хватает env vars для запуска LLM."""


class LLMProviderError(RuntimeError):
    """Провайдер вернул ошибку."""


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    text: str


@dataclass
class LLMResponse:
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    raw: dict = field(default_factory=dict)


class LLMClient:
    """Абстрактный интерфейс. Реализации: YandexGPTClient, (позже) OpenAICompatibleClient."""

    async def chat(self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int = 1500) -> LLMResponse:
        raise NotImplementedError


class YandexGPTClient(LLMClient):
    def __init__(self, api_key: str, folder_id: str, model: str = "yandexgpt/latest"):
        if not api_key or not folder_id:
            raise LLMConfigurationError("YANDEX_API_KEY и YANDEX_FOLDER_ID должны быть заполнены в .env")
        self.api_key = api_key
        self.folder_id = folder_id
        self.model_uri = f"gpt://{folder_id}/{model}"

    async def chat(self, messages: list[ChatMessage], *, temperature: float = 0.3, max_tokens: int = 1500) -> LLMResponse:
        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": max_tokens,
            },
            "messages": [{"role": m.role, "text": m.text} for m in messages],
        }
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "x-folder-id": self.folder_id,
            "Content-Type": "application/json",
        }

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(YANDEX_COMPLETION_URL, json=payload, headers=headers) as resp:
                body = await resp.json()
                if resp.status >= 400:
                    logger.error(f"YandexGPT error {resp.status}: {body}")
                    raise LLMProviderError(f"YandexGPT {resp.status}: {body}")

        try:
            alt = body["result"]["alternatives"][0]
            text = alt["message"]["text"]
            usage = body["result"].get("usage", {})
            return LLMResponse(
                text=text,
                input_tokens=int(usage.get("inputTextTokens", 0)) or None,
                output_tokens=int(usage.get("completionTokens", 0)) or None,
                raw=body,
            )
        except (KeyError, IndexError) as e:
            raise LLMProviderError(f"Неожиданный ответ YandexGPT: {body}") from e


def get_llm_client() -> LLMClient:
    """Фабрика провайдера. Пока — только YandexGPT."""
    return YandexGPTClient(
        api_key=YANDEX_API_KEY,
        folder_id=YANDEX_FOLDER_ID,
        model=YANDEX_GPT_MODEL,
    )
