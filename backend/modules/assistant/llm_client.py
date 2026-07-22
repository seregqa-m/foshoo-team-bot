"""
Провайдер-агностичная обёртка для LLM с поддержкой function calling.

MVP-реализация — YandexGPT через OpenAI-совместимый endpoint Yandex AI Studio
(`https://ai.api.cloud.yandex.net/v1/chat/completions`). Формат сообщений и
tool_calls — стандартный OpenAI, поэтому позже подменить провайдера (Claude
через посредника, OpenAI напрямую, OSS-модели) можно без переписывания
вызывающего кода.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

from config import (
    YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_GPT_MODEL,
    LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_REASONING_EFFORT,
)

logger = logging.getLogger(__name__)

YANDEX_OPENAI_URL = "https://ai.api.cloud.yandex.net/v1/chat/completions"


class LLMConfigurationError(RuntimeError):
    """Не хватает env vars для запуска LLM."""


class LLMProviderError(RuntimeError):
    """Провайдер вернул ошибку."""


@dataclass
class ChatMessage:
    """OpenAI-style сообщение. role ∈ {"system","user","assistant","tool"}.

    Для role="tool" обязательно tool_call_id.
    Для role="assistant" с tool_calls — content может быть пустым, tool_calls
    заполнен структурами вида {id, type: "function", function: {name, arguments}}.
    """
    role: str
    text: str = ""
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict]] = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _message_to_openai(m: ChatMessage) -> dict:
    """Сконвертировать ChatMessage в OpenAI-совместимый JSON."""
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.text}
    if m.role == "assistant" and m.tool_calls:
        return {"role": "assistant", "content": m.text or "", "tool_calls": m.tool_calls}
    return {"role": m.role, "content": m.text}


class LLMClient:
    """Абстрактный интерфейс LLM. Реализации: YandexGPTClient и (позже) другие."""

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.3,
        max_tokens: int = 1500,
    ) -> LLMResponse:
        raise NotImplementedError


class YandexGPTClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        folder_id: str,
        model: str = "yandexgpt/latest",
        temperature: float = 0.3,
        max_tokens: int = 1500,
        reasoning_effort: str = "",
    ):
        if not api_key or not folder_id:
            raise LLMConfigurationError("YANDEX_API_KEY и YANDEX_FOLDER_ID должны быть заполнены в .env")
        self.api_key = api_key
        self.folder_id = folder_id
        self.model_uri = f"gpt://{folder_id}/{model}"
        self.default_temperature = temperature
        self.default_max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort  # "" = не передаём

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model_uri,
            "messages": [_message_to_openai(m) for m in messages],
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "OpenAI-Project": self.folder_id,
            "Content-Type": "application/json",
        }

        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(YANDEX_OPENAI_URL, json=payload, headers=headers) as resp:
                body = await resp.json()
                if resp.status >= 400:
                    logger.error(f"YandexGPT (OpenAI) error {resp.status}: {body}")
                    raise LLMProviderError(f"YandexGPT {resp.status}: {body}")

        try:
            choice = body["choices"][0]
            msg = choice.get("message", {})
            text = msg.get("content") or ""
            raw_tool_calls = msg.get("tool_calls") or []
            parsed_tools: list[ToolCall] = []
            for tc in raw_tool_calls:
                fn = tc.get("function", {})
                args_str = fn.get("arguments") or "{}"
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    logger.warning(f"tool_call arguments not valid JSON: {args_str}")
                    args = {}
                parsed_tools.append(ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=args if isinstance(args, dict) else {},
                ))
            usage = body.get("usage", {})
            return LLMResponse(
                text=text,
                tool_calls=parsed_tools,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                finish_reason=choice.get("finish_reason"),
                raw=body,
            )
        except (KeyError, IndexError) as e:
            raise LLMProviderError(f"Неожиданный ответ YandexGPT: {body}") from e


def get_llm_client() -> LLMClient:
    """Фабрика провайдера. Пока — только YandexGPT через OpenAI-compat endpoint."""
    return YandexGPTClient(
        api_key=YANDEX_API_KEY,
        folder_id=YANDEX_FOLDER_ID,
        model=YANDEX_GPT_MODEL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        reasoning_effort=LLM_REASONING_EFFORT,
    )
