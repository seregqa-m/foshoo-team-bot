import asyncio
import hashlib
import hmac
import json
import os
import time
import unittest
from urllib.parse import urlencode
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

with patch.dict(os.environ, {"BOT_TOKEN": "123456:offline-test-token", "DATABASE_URL": "sqlite://", "GOOGLE_CALENDAR_JSON": "/missing"}, clear=True), patch("dotenv.load_dotenv"):
    from core.access import verify_init_data, authorize_api, TelegramUser
    from core.database import Base
    from modules.calendar.models import CalendarEvent
    from modules.polling.models import Poll, PollVote
    from modules.polling.services import PollingService
    from modules.availability.models import AvailabilityCampaign, AvailabilityPoll, AvailabilityVote
    from modules.assistant.services import AssistantService, _make_action_token
    from bot import _handle_availability_answer

from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def signed_data(token="test-token", user_id=42, auth_date=None):
    fields = {"auth_date": str(auth_date or int(time.time())), "user": json.dumps({"id": user_id, "username": "actor"})}
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(key, "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class AccessTests(unittest.TestCase):
    def setUp(self):
        role = patch('core.access.is_super_admin', AsyncMock(return_value=False))
        role.start()
        self.addCleanup(role.stop)
        from core.access import _access_cache
        _access_cache.clear()

    def test_signature_age_and_tampering(self):
        valid = signed_data(auth_date=1000)
        self.assertEqual(verify_init_data(valid, bot_token="test-token", now=1001).id, 42)
        for raw, now in [(valid + "&user_id=1", 1001), (valid, 100000), (valid, 900), ("", 1001), (valid + "&auth_date=1000", 1001)]:
            with self.assertRaises(HTTPException):
                verify_init_data(raw, bot_token="test-token", now=now)

    def test_permissions_and_spoofing(self):
        app = FastAPI(dependencies=[Depends(authorize_api)])
        @app.post("/api/calendar/events")
        @app.post("/api/finance/expense")
        @app.get("/api/calendar/events")
        def endpoint():
            return {"ok": True}
        client = TestClient(app)
        self.assertEqual(client.get('/api/calendar/events').status_code, 401)
        with patch('core.access.verify_init_data', return_value=TelegramUser(42, 'actor')), patch('core.access._is_group_admin', AsyncMock(return_value=False)), patch('core.access._known_actor', return_value=True):
            self.assertEqual(client.get('/api/calendar/events').status_code, 200)
            self.assertEqual(client.post('/api/calendar/events').status_code, 403)
            self.assertEqual(client.post('/api/finance/expense', json={'user_id': 99}).status_code, 403)
            self.assertEqual(client.post('/api/finance/expense?user_id=99', json={'user_id': 42}).status_code, 403)
            self.assertEqual(client.post('/api/finance/expense', json={'username': 'admin'}).status_code, 403)
            self.assertEqual(client.post('/api/finance/expense', json={'user_id': 42}).status_code, 200)
            self.assertEqual(client.post('/api/finance/expense', headers={'Content-Type': 'application/json'}).status_code, 200)
        from core.access import _access_cache
        _access_cache.clear()
        with patch('core.access.verify_init_data', return_value=TelegramUser(42, 'actor')), patch('core.access._is_group_admin', AsyncMock(return_value=False)), patch('core.access._known_actor', side_effect=HTTPException(503, 'unavailable')):
            self.assertEqual(client.get('/api/calendar/events').status_code, 503)


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_vote_retraction_and_revote(self):
        service = PollingService(self.db)
        poll = service.create_poll('Test', 42)
        service.vote(poll.id, 42, 'yes')
        service.vote(poll.id, 42, 'retracted')
        self.assertEqual(service.get_poll_results(poll.id)['total_votes'], 0)
        service.vote(poll.id, 42, 'no')
        service.vote(poll.id, 42, 'no')
        self.assertEqual(service.get_poll_results(poll.id)['results']['no'], 1)

    async def test_availability_retraction_marks_actor_as_non_voter(self):
        poll = AvailabilityPoll()
        self.db.add(poll)
        self.db.commit()
        answer = SimpleNamespace(user=SimpleNamespace(id=42, username='actor'), option_ids=[0])
        _handle_availability_answer(answer, poll, self.db)
        self.assertEqual(self.db.query(AvailabilityVote).count(), 1)
        answer.option_ids = []
        _handle_availability_answer(answer, poll, self.db)
        self.assertEqual(self.db.query(AvailabilityVote).count(), 0)

    async def test_retraction_clears_sheet_with_previous_username(self):
        from modules.availability.models import AvailabilityPollOption
        from datetime import datetime
        from unittest.mock import MagicMock
        event = CalendarEvent(start_time=datetime(2026, 10, 1, 19))
        poll = AvailabilityPoll()
        self.db.add_all([event, poll]); self.db.commit()
        self.db.add(AvailabilityPollOption(poll_id=poll.id, option_index=0, calendar_event_id=event.id))
        self.db.add(AvailabilityVote(poll_id=poll.id, user_id=42, username='actor'))
        self.db.commit()
        answer = SimpleNamespace(user=SimpleNamespace(id=42, username=None), option_ids=[])
        client = MagicMock()
        with patch('config.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), patch('sheets_client.SheetsClient', return_value=client):
            _handle_availability_answer(answer, poll, self.db)
        self.assertEqual(self.db.query(AvailabilityVote).count(), 0)
        self.assertEqual(client.record_poll_answer.call_args.args[0], 'actor')
        self.assertEqual(client.record_poll_answer.call_args.args[2], 'retracted')

    async def test_action_replay_returns_result_across_sessions(self):
        handler = AsyncMock(return_value={'added': True})
        tool = SimpleNamespace(handler=handler, safety_level='confirm')
        token = _make_action_token(user_id=42, tool_name='add_expense', args={})
        with patch('modules.assistant.services.get_tool', return_value=tool):
            one = await AssistantService(self.db).execute_pending(user_id=42, action_token=token)
            with self.Session() as other:
                two = await AssistantService(other).execute_pending(user_id=42, action_token=token)
            self.assertEqual(one, two)
            handler.assert_awaited_once()

    async def test_action_in_progress_or_uncertain_never_repeats(self):
        started = asyncio.Event()
        release = asyncio.Event()
        async def slow(*args):
            started.set()
            await release.wait()
            raise RuntimeError('external response lost')
        handler = AsyncMock(side_effect=slow)
        token = _make_action_token(user_id=42, tool_name='add_expense', args={})
        with patch('modules.assistant.services.get_tool', return_value=SimpleNamespace(handler=handler, safety_level='confirm')):
            pending = asyncio.create_task(AssistantService(self.db).execute_pending(user_id=42, action_token=token))
            await started.wait()
            with self.Session() as other:
                with self.assertRaises(HTTPException) as error:
                    await AssistantService(other).execute_pending(user_id=42, action_token=token)
                self.assertEqual(error.exception.status_code, 409)
            release.set()
            with self.assertRaises(RuntimeError):
                await pending
            with self.assertRaises(HTTPException):
                await AssistantService(self.db).execute_pending(user_id=42, action_token=token)
            handler.assert_awaited_once()

    async def test_action_user_and_admin_permissions(self):
        handler = AsyncMock()
        token = _make_action_token(user_id=42, tool_name='create_event', args={})
        with patch('modules.assistant.services.get_tool', return_value=SimpleNamespace(handler=handler, safety_level='confirm')):
            with self.assertRaises(ValueError):
                await AssistantService(self.db).execute_pending(user_id=43, action_token=token, is_admin=True)
            with self.assertRaises(HTTPException):
                await AssistantService(self.db).execute_pending(user_id=42, action_token=token)
        handler.assert_not_called()


class AccessLatencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from core import access
        self.access = access
        access._access_cache.clear()
        role = patch("core.access.is_super_admin", AsyncMock(return_value=False))
        role.start()
        self.addCleanup(role.stop)

    async def test_slow_user_does_not_block_cached_or_uncached_user(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def group_admin(user_id):
            if user_id == 1:
                entered.set()
                await release.wait()
            return True
        self.access._access_cache[(2, "cached")] = (time.monotonic() + 60, True, False)
        with patch("core.access._is_group_admin", side_effect=group_admin):
            slow = asyncio.create_task(self.access._permissions(TelegramUser(1, "slow")))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                cached = await asyncio.wait_for(self.access._permissions(TelegramUser(2, "cached")), .2)
                fresh = await asyncio.wait_for(self.access._permissions(TelegramUser(3, "fresh")), .2)
                self.assertEqual(cached, (True, False, False))
                self.assertEqual(fresh, (True, True, False))
                self.assertFalse(slow.done())
            finally:
                release.set()
                await slow

    async def test_telegram_timeout_is_not_cached_and_retry_succeeds(self):
        import bot
        async def stalled(*args, **kwargs):
            await asyncio.Event().wait()
        with patch("core.access.GROUP_CHAT_ID", -123), patch("core.access.TELEGRAM_ACCESS_TIMEOUT", .01), patch.object(bot.bot, "get_chat_member", side_effect=stalled):
            with self.assertLogs("core.access", level="WARNING") as logs:
                with self.assertRaises(HTTPException) as error:
                    await self.access._permissions(TelegramUser(1, "actor"))
            self.assertEqual(error.exception.status_code, 503)
            self.assertIn("stage=telegram outcome=timeout", " ".join(logs.output))
            self.assertFalse(self.access._access_cache)
        with patch("core.access._is_group_admin", AsyncMock(return_value=True)):
            self.assertEqual(await self.access._permissions(TelegramUser(1, "actor")), (True, True, False))

    async def test_sheets_timeout_does_not_reuse_expired_access(self):
        import threading
        release = threading.Event()
        def stalled(username):
            release.wait(1)
            return True
        self.access._access_cache[(1, "actor")] = (time.monotonic() - 1, True, True)
        try:
            with patch("core.access._is_group_admin", AsyncMock(return_value=False)), patch("core.access._known_actor", side_effect=stalled), patch("core.access.SHEETS_ACCESS_TIMEOUT", .01):
                with self.assertRaises(HTTPException) as error:
                    await self.access._permissions(TelegramUser(1, "actor"))
                self.assertEqual(error.exception.status_code, 503)
                self.assertLess(self.access._access_cache[(1, "actor")][0], time.monotonic())
        finally:
            release.set()

    async def test_telegram_failure_logs_type_without_sensitive_message(self):
        import bot
        with patch("core.access.GROUP_CHAT_ID", -123), patch.object(bot.bot, "get_chat_member", side_effect=RuntimeError("private-token")):
            with self.assertLogs("core.access", level="WARNING") as logs:
                with self.assertRaises(HTTPException) as error:
                    await self.access._permissions(TelegramUser(1, "actor"))
            self.assertEqual(error.exception.status_code, 503)
            self.assertNotIn("private-token", " ".join(logs.output))
            self.assertIn("RuntimeError", " ".join(logs.output))
            self.assertFalse(self.access._access_cache)

    async def test_superadmin_revocation_is_checked_even_with_cached_access(self):
        with patch("core.access.is_super_admin", AsyncMock(side_effect=[True, False])), patch("core.access._is_group_admin", AsyncMock(return_value=False)), patch("core.access._known_actor", return_value=False):
            user = TelegramUser(1, "actor")
            self.assertEqual(await self.access._permissions(user), (True, True, True))
            self.assertEqual(await self.access._permissions(user), (False, False, False))
