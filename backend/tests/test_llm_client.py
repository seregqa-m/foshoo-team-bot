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
            ChatMessage, LLMProviderError, YandexGPTClient,
        )


class LLMResponseTests(unittest.IsolatedAsyncioTestCase):
    async def chat(self, message, finish_reason="stop"):
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value={
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        })
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        with patch("modules.assistant.llm_client.aiohttp.ClientSession") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=session)
            client = YandexGPTClient(api_key="test-key", folder_id="test-folder")
            return await client.chat([ChatMessage(role="user", text="Тест")])

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


if __name__ == "__main__":
    unittest.main()
