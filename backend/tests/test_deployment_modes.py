import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://',
                             'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    import main

from fastapi.testclient import TestClient
from fastapi import HTTPException
from modules.assistant import router as assistant_router


class DeploymentModesTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_assistant_rejects_chat_and_old_confirmations(self):
        with patch('modules.assistant.router.ASSISTANT_ENABLED', False), \
                patch('modules.assistant.router.AssistantService') as service:
            for handler, request in (
                (assistant_router.chat, assistant_router.ChatRequest(user_id=42, message='Привет')),
                (assistant_router.execute, assistant_router.ExecuteRequest(user_id=42, action_token='old')),
            ):
                with self.assertRaises(HTTPException) as raised:
                    await handler(request, None, None)
                self.assertEqual(raised.exception.status_code, 503)
            service.assert_not_called()

    async def start(self, recovery, automation):
        with patch('main.RECOVERY_MODE', recovery), patch('main.POLL_AUTOMATION_ENABLED', automation), \
                patch('main.init_db'), patch('main.run_migrations'), \
                patch('modules.admin.services.bootstrap_superadmin'), patch('core.database.SessionLocal'), \
                patch('main._run_bot', new_callable=AsyncMock) as bot, \
                patch('main.sync_calendar_background', new_callable=AsyncMock) as calendar, \
                patch('main.sync_finance_background', new_callable=AsyncMock) as finance, \
                patch('main.attendance_sync_background', new_callable=AsyncMock) as attendance, \
                patch('main.poll_reminder_background', new_callable=AsyncMock) as reminders:
            await main.startup()
            await asyncio.gather(*main.app.state.tasks)
            return [f.call_count for f in (bot, calendar, finance, attendance, reminders)]

    async def test_recovery_starts_no_external_tasks(self):
        self.assertEqual(await self.start(True, True), [0, 0, 0, 0, 0])

    async def test_live_without_automation_still_polls_and_syncs(self):
        self.assertEqual(await self.start(False, False), [1, 1, 1, 1, 0])

    async def test_normal_mode_starts_one_of_each(self):
        self.assertEqual(await self.start(False, True), [1, 1, 1, 1, 1])

    async def test_recovery_blocks_reads_and_writes_before_auth_or_external_calls(self):
        # Without the context manager TestClient does not run DB startup.
        with patch('main.RECOVERY_MODE', True):
            client = TestClient(main.app)
            self.addCleanup(client.close)
            self.assertEqual(client.get('/health').json()['status'], 'recovery')
            for method, path in [('get', '/api/auth/check'), ('get', '/api/sheets/schedule'),
                                 ('post', '/api/assistant/chat'), ('post', '/api/calendar/sync')]:
                self.assertEqual(getattr(client, method)(path).status_code, 503)
