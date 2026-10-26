"""
Провайдер-агностичная обёртка для LLM с поддержкой function calling.

Cloud.ru и Yandex AI Studio используют OpenAI-совместимые сообщения и tool_calls.
Выбор провайдера не меняет подтверждения действий и права пользователя.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

from config import (
    YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_GPT_MODEL,
    LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_REASONING_EFFORT, LLM_ENABLED,
    LLM_PROVIDER, CLOUDRU_API_KEY, CLOUDRU_MODEL,
)

logger = logging.getLogger(__name__)

YANDEX_OPENAI_URL = "https://ai.api.cloud.yandex.net/v1/chat/completions"
CLOUDRU_OPENAI_URL = "https://foundation-models.api.cloud.ru/v1/chat/completions"


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
    """Абстрактный интерфейс LLM."""

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


class OpenAICompatibleClient(LLMClient):
    def __init__(
        self,
        *,
        url: str,
        headers: dict[str, str],
        model: str,
        provider_name: str,
        token_parameter: str = "max_tokens",
        single_tool_call: bool = False,
        temperature: float = 0.3,
        max_tokens: int = 1500,
        reasoning_effort: str = "",
    ):
        self.url = url
        self.headers = headers
        self.model_uri = model
        self.provider_name = provider_name
        self.token_parameter = token_parameter
        self.single_tool_call = single_tool_call
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
        if not LLM_ENABLED:
            raise LLMConfigurationError("LLM отключена")
        payload: dict[str, Any] = {
            "model": self.model_uri,
            "messages": [_message_to_openai(m) for m in messages],
            "temperature": temperature if temperature is not None else self.default_temperature,
            self.token_parameter: max_tokens if max_tokens is not None else self.default_max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
            if self.single_tool_call:
                payload["parallel_tool_calls"] = False

        timeout = aiohttp.ClientTimeout(total=45)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.url, json=payload, headers=self.headers) as resp:
                    if resp.status >= 400:
                        # Provider error bodies can echo prompts or credentials.
                        logger.error("%s HTTP error %s", self.provider_name, resp.status)
                        raise LLMProviderError(f"{self.provider_name}: HTTP {resp.status}")
                    body = await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise LLMProviderError(f"{self.provider_name}: ошибка соединения или ответа API") from exc

        try:
            choice = body["choices"][0]
            msg = choice.get("message", {})
            finish_reason = choice.get("finish_reason")
            # Only content is a public reply. reasoning_content must never be
            # used as an answer or as the preface to an action confirmation.
            text = msg.get("content") or ""
            if not text.strip() and not msg.get("tool_calls"):
                logger.warning(
                    "LLM returned no public answer or tool calls. finish_reason=%s",
                    finish_reason,
                )
                raise LLMProviderError(f"{self.provider_name} не вернул готовый ответ или вызов инструмента")
            raw_tool_calls = msg.get("tool_calls") or []
            parsed_tools: list[ToolCall] = []
            for tc in raw_tool_calls:
                fn = tc.get("function", {})
                args_str = fn.get("arguments") or "{}"
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    raise LLMProviderError("Некорректные аргументы инструмента") from None
                if not isinstance(args, dict) or not tc.get("id") or not fn.get("name"):
                    raise LLMProviderError("Некорректный вызов инструмента")
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
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMProviderError(f"Неожиданный формат ответа {self.provider_name}") from e


class YandexGPTClient(OpenAICompatibleClient):
    def __init__(self, api_key: str, folder_id: str, model: str = "yandexgpt/latest",
                 temperature: float = 0.3, max_tokens: int = 1500, reasoning_effort: str = ""):
        if not api_key or not folder_id:
            raise LLMConfigurationError("YANDEX_API_KEY и YANDEX_FOLDER_ID должны быть заполнены в .env")
        super().__init__(
            url=YANDEX_OPENAI_URL, provider_name="YandexGPT",
            headers={"Authorization": f"Api-Key {api_key}", "OpenAI-Project": folder_id,
                     "Content-Type": "application/json"},
            model=f"gpt://{folder_id}/{model}", temperature=temperature,
            max_tokens=max_tokens, reasoning_effort=reasoning_effort,
        )


class CloudRuClient(OpenAICompatibleClient):
    def __init__(self, api_key: str, model: str = "openai/gpt-oss-120b",
                 temperature: float = 0.3, max_tokens: int = 4096, reasoning_effort: str = ""):
        if not api_key.strip() or not model.strip():
            raise LLMConfigurationError("CLOUDRU_API_KEY и CLOUDRU_MODEL должны быть заполнены в .env")
        super().__init__(
            url=CLOUDRU_OPENAI_URL, provider_name="Cloud.ru",
            headers={"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"},
            model=model.strip(), temperature=temperature, max_tokens=max_tokens,
            reasoning_effort=reasoning_effort, token_parameter="max_completion_tokens",
            single_tool_call=True,
        )


def get_llm_client() -> LLMClient:
    """Фабрика провайдера; никогда не переключается на другой сервис неявно."""
    if not LLM_ENABLED:
        raise LLMConfigurationError("LLM отключена")
    if LLM_PROVIDER == "cloudru":
        return CloudRuClient(
            api_key=CLOUDRU_API_KEY, model=CLOUDRU_MODEL,
            temperature=LLM_TEMPERATURE, max_tokens=LLM_MAX_TOKENS,
            reasoning_effort=LLM_REASONING_EFFORT,
        )
    if LLM_PROVIDER != "yandex":
        raise LLMConfigurationError("Неизвестный LLM_PROVIDER: ожидается cloudru или yandex")
    return YandexGPTClient(
        api_key=YANDEX_API_KEY,
        folder_id=YANDEX_FOLDER_ID,
        model=YANDEX_GPT_MODEL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        reasoning_effort=LLM_REASONING_EFFORT,
    )
