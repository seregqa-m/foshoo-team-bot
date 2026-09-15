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
        with patch('core.access.verify_init_data', return_value=TelegramUser(42, 'actor')), patch('core.access.is_admin', AsyncMock(return_value=False)), patch('core.access._known_actor', return_value=True):
            self.assertEqual(client.get('/api/calendar/events').status_code, 200)
            self.assertEqual(client.post('/api/calendar/events').status_code, 403)
            self.assertEqual(client.post('/api/finance/expense', json={'user_id': 99}).status_code, 403)
            self.assertEqual(client.post('/api/finance/expense', json={'username': 'admin'}).status_code, 403)
            self.assertEqual(client.post('/api/finance/expense', json={'user_id': 42}).status_code, 200)
        with patch('core.access.verify_init_data', return_value=TelegramUser(42, 'actor')), patch('core.access.is_admin', AsyncMock(return_value=False)), patch('core.access._known_actor', side_effect=HTTPException(503, 'unavailable')):
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
