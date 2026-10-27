import json
import os
import unittest
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': 'offline-test-token'}, clear=True), patch('dotenv.load_dotenv'):
    from modules.assistant.llm_client import LLMResponse, LLMProviderError, LLMConfigurationError
    from modules.moderation.classifier import classify, fingerprint, Verdict


class ClassifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_client_receives_only_comment_data_without_tools(self):
        comment = 'Есть возможность хорошо заработать за два-три часа. Нечего сложного справится любой.10 000 руб.'
        client = AsyncMock()
        client.chat.return_value = LLMResponse(text='{"verdict":"spam","reason":"Обещание легкого заработка"}', finish_reason='stop')
        with patch('modules.moderation.classifier.get_llm_client', return_value=client) as factory:
            result = await classify({'text': comment, 'links': ['https://example.org'],
                                     'sender': {'name': 'private-name', 'username': 'private-username'}})
        factory.assert_called_once_with()
        self.assertEqual(result, Verdict('spam', 'Обещание легкого заработка'))
        messages = client.chat.call_args.args[0]
        self.assertEqual([m.role for m in messages], ['system', 'user'])
        self.assertEqual(json.loads(messages[1].text), {'text': comment, 'links': ['https://example.org']})
        self.assertNotIn('tools', client.chat.call_args.kwargs)
        self.assertNotIn('private-name', messages[1].text)

    async def test_model_can_allow_or_request_human_review(self):
        for verdict in ('allow', 'review'):
            client = AsyncMock()
            client.chat.return_value = LLMResponse(text=json.dumps({'verdict': verdict, 'reason': 'Причина'}), finish_reason='stop')
            with patch('modules.moderation.classifier.get_llm_client', return_value=client):
                self.assertEqual((await classify({'text': 'Комментарий'})).verdict, verdict)

    async def test_malformed_truncated_and_tool_answers_are_not_deletion_verdicts(self):
        for text in ('not json', '[]', 'null', '{}', '{"verdict":true,"reason":"x"}',
                     '{"verdict":"spam","reason":""}', '{"verdict":"spam","reason":123}',
                     '{"verdict":"spam","reason":"x","extra":true}', '{"verdict":"unknown","reason":"x"}'):
            client = AsyncMock()
            client.chat.return_value = LLMResponse(text=text, finish_reason='stop')
            with self.subTest(text=text), patch('modules.moderation.classifier.get_llm_client', return_value=client):
                with self.assertRaises(LLMProviderError):
                    await classify({'text': 'Комментарий'})
        for response in (
            LLMResponse(text='{"verdict":"spam","reason":"x"}', finish_reason='length'),
            LLMResponse(text='{"verdict":"spam","reason":"x"}', finish_reason='stop', tool_calls=[object()]),
        ):
            client = AsyncMock()
            client.chat.return_value = response
            with patch('modules.moderation.classifier.get_llm_client', return_value=client), self.assertRaises(LLMProviderError):
                await classify({'text': 'Комментарий'})

    async def test_disabled_llm_has_no_regex_fallback(self):
        with patch('modules.assistant.llm_client.LLM_ENABLED', False), self.assertRaises(LLMConfigurationError):
            await classify({'text': 'Заработок без опыта, 10000 рублей, пишите мне'})

    def test_fingerprint_matches_cosmetics_but_preserves_meaning_and_links(self):
        original = fingerprint({'text': 'Лёгкий заработок 10 000 руб.'})
        self.assertEqual(original, fingerprint({'text': ' ЛЕГКИЙ зара\u200bботок １０\u00a0０００ руб.\n',
                                                'sender': {'name': 'Другой'}}))
        for text in ('Не лёгкий заработок 10 000 руб.', '«Лёгкий заработок 10 000 руб.»',
                     'Лёгкий заработок 100 000 руб.'):
            self.assertNotEqual(original, fingerprint({'text': text}))
        self.assertNotEqual(original, fingerprint({'text': 'Лёгкий заработок 10 000 руб.', 'links': ['https://example.org']}))
