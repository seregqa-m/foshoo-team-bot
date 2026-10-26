"""Offline checks for the boundary between model reasoning and public replies.

Run from the repository root:
    PYTHONPATH=backend python -m unittest discover -s backend/tests -v
"""
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Import configuration without reading .env or requiring real credentials.
with patch.dict(os.environ, {"BOT_TOKEN": "offline-test-token"}, clear=True):
    with patch("dotenv.load_dotenv"):
        from modules.assistant.llm_client import (
            ChatMessage, LLMProviderError, LLMConfigurationError, YandexGPTClient, CloudRuClient,
            CLOUDRU_OPENAI_URL, get_llm_client,
        )


class LLMResponseTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self):
        return YandexGPTClient(api_key="test-key", folder_id="test-folder")

    async def chat(self, message, finish_reason="stop"):
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value={
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        })
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        with patch("modules.assistant.llm_client.LLM_ENABLED", True), patch("modules.assistant.llm_client.aiohttp.ClientSession") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=session)
            client = self.make_client()
            return await client.chat([ChatMessage(role="user", text="Тест")])

    async def test_disabled_llm_never_constructs_a_session_even_with_valid_keys(self):
        with patch('modules.assistant.llm_client.LLM_ENABLED', False), patch('modules.assistant.llm_client.aiohttp.ClientSession') as factory:
            with self.assertRaises(LLMConfigurationError):
                get_llm_client()
            client = self.make_client()
            with self.assertRaises(LLMConfigurationError):
                await client.chat([ChatMessage(role='user', text='Тест')])
            factory.assert_not_called()

    async def test_final_answer_excludes_reasoning(self):
        result = await self.chat({
            "content": "Готово к подтверждению.",
            "reasoning_content": "PRIVATE_REASONING",
        })
        self.assertEqual(result.text, "Готово к подтверждению.")
        self.assertEqual(result.input_tokens, 10)
        self.assertEqual(result.output_tokens, 20)

    async def test_reasoning_only_is_rejected_without_logging_it(self):
        for reason in ("stop", "length"):
            with self.subTest(finish_reason=reason):
                with self.assertLogs("modules.assistant.llm_client", level="WARNING") as logs:
                    with self.assertRaises(LLMProviderError) as raised:
                        await self.chat({
                            "content": None,
                            "reasoning_content": "PRIVATE_REASONING",
                        }, finish_reason=reason)
                self.assertNotIn("PRIVATE_REASONING", str(raised.exception))
                self.assertNotIn("PRIVATE_REASONING", "\n".join(logs.output))

    async def test_tool_call_without_final_text_is_preserved(self):
        result = await self.chat({
            "content": None,
            "reasoning_content": "PRIVATE_REASONING",
            "tool_calls": [{
                "id": "call-test",
                "type": "function",
                "function": {"name": "add_expense", "arguments": '{"amount": 5000}'},
            }],
        }, finish_reason="tool_calls")
        self.assertEqual(result.text, "")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].id, "call-test")
        self.assertEqual(result.tool_calls[0].name, "add_expense")
        self.assertEqual(result.tool_calls[0].arguments, {"amount": 5000})

    async def test_empty_answers_are_rejected(self):
        for content in (None, "", "  \n  "):
            with self.subTest(content=content):
                with self.assertLogs("modules.assistant.llm_client", level="WARNING"):
                    with self.assertRaises(LLMProviderError):
                        await self.chat({"content": content})

    async def test_malformed_tool_arguments_are_rejected(self):
        for arguments in ('{broken', '[]', 'null'):
            with self.subTest(arguments=arguments), self.assertRaises(LLMProviderError):
                await self.chat({"tool_calls": [{"id": "call-1", "function": {
                    "name": "add_expense", "arguments": arguments,
                }}]})


class CloudRuTests(LLMResponseTests):
    def make_client(self):
        return CloudRuClient(api_key="test-key")

    async def test_request_preserves_tool_result_and_uses_cloudru_auth(self):
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value={"choices": [{"message": {"content": "Ответ"}}]})
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        calls = [{"id": "call-1", "type": "function", "function": {
            "name": "get_events_in_range", "arguments": "{}"}}]
        schema = [{"type": "function", "function": {"name": "get_events_in_range"}}]
        with patch("modules.assistant.llm_client.LLM_ENABLED", True), \
                patch("modules.assistant.llm_client.aiohttp.ClientSession") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=session)
            await self.make_client().chat([
                ChatMessage(role="assistant", tool_calls=calls),
                ChatMessage(role="tool", tool_call_id="call-1", text='{"events": []}'),
            ], tools=schema)
        args, kwargs = session.post.call_args
        self.assertEqual(args, (CLOUDRU_OPENAI_URL,))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertNotIn("OpenAI-Project", kwargs["headers"])
        payload = kwargs["json"]
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")
        self.assertEqual(payload["max_completion_tokens"], 4096)
        self.assertNotIn("max_tokens", payload)
        self.assertFalse(payload["parallel_tool_calls"])
        self.assertEqual(payload["tools"], schema)
        self.assertEqual(payload["messages"][0]["tool_calls"], calls)
        self.assertEqual(payload["messages"][1]["tool_call_id"], "call-1")

    async def test_http_errors_do_not_read_or_expose_provider_body(self):
        response = MagicMock(status=401)
        response.json = AsyncMock(return_value={"error": "PRIVATE_DATA"})
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        with patch("modules.assistant.llm_client.LLM_ENABLED", True), \
                patch("modules.assistant.llm_client.aiohttp.ClientSession") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=session)
            with self.assertLogs("modules.assistant.llm_client", level="ERROR") as logs:
                with self.assertRaises(LLMProviderError) as error:
                    await self.make_client().chat([ChatMessage(role="user", text="Тест")])
        self.assertIn("401", str(error.exception))
        self.assertNotIn("PRIVATE_DATA", str(error.exception) + str(logs.output))
        response.json.assert_not_called()

    def test_factory_selects_cloudru_without_yandex_credentials(self):
        with patch("modules.assistant.llm_client.LLM_ENABLED", True), \
                patch("modules.assistant.llm_client.LLM_PROVIDER", "cloudru"), \
                patch("modules.assistant.llm_client.CLOUDRU_API_KEY", "test-key"):
            self.assertIsInstance(get_llm_client(), CloudRuClient)

    def test_missing_key_and_unknown_provider_fail_closed(self):
        with self.assertRaises(LLMConfigurationError):
            CloudRuClient(api_key="")
        with patch("modules.assistant.llm_client.LLM_ENABLED", True), \
                patch("modules.assistant.llm_client.LLM_PROVIDER", "typo"):
            with self.assertRaises(LLMConfigurationError):
                get_llm_client()


if __name__ == "__main__":
    unittest.main()
