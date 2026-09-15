import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

with patch.dict(os.environ, {"BOT_TOKEN": "123456:offline-test-token", "DATABASE_URL": "sqlite://", "GOOGLE_CALENDAR_JSON": "/missing"}, clear=True), patch("dotenv.load_dotenv"):
    from core.database import Base
    from core.time import as_local
    from modules.calendar.google_client import GoogleCalendarClient
    from modules.calendar.services import CalendarService
    from modules.calendar.models import CalendarEvent
    from modules.polling.models import Poll
    from modules.finance.models import ExpenseLog
    from modules.finance.reconciliation import reconcile, fingerprint
    from finance_router import delete_transaction, add_expense, ExpenseRequest
    from sheets_client import SheetsClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException


class CalendarFetchTests(unittest.TestCase):
    def test_all_pages_share_one_window(self):
        client = GoogleCalendarClient.__new__(GoogleCalendarClient)
        client.service = MagicMock()
        request = client.service.events.return_value.list
        request.return_value.execute.side_effect = [
            {'items': [{'id': 'one'}], 'nextPageToken': 'page2'},
            {'items': [{'id': 'two'}]},
        ]
        self.assertEqual(len(client.get_events('test')), 2)
        self.assertEqual(request.call_args_list[1].kwargs['pageToken'], 'page2')
        self.assertEqual(request.call_args_list[0].kwargs['timeMin'], request.call_args_list[1].kwargs['timeMin'])
        self.assertIsNotNone(client.sync_window)

    def test_failed_page_never_returns_partial_snapshot(self):
        client = GoogleCalendarClient.__new__(GoogleCalendarClient)
        client.service = MagicMock()
        client.service.events.return_value.list.return_value.execute.side_effect = [
            {'items': [{'id': 'one'}], 'nextPageToken': 'page2'}, RuntimeError('timeout')]
        with self.assertRaises(RuntimeError):
            client.get_events('test')
        self.assertFalse(hasattr(client, 'sync_window'))


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_offset_roundtrip_and_legacy_wall_time(self):
        e = CalendarEvent(google_event_id='tz', start_time=datetime.fromisoformat('2026-09-16T16:00:00+00:00'), end_time=datetime(2026, 9, 16, 21))
        self.db.add(e)
        self.db.commit()
        self.db.refresh(e)
        self.assertEqual(e.start_time.isoformat(), '2026-09-16T19:00:00+03:00')
        self.assertEqual(e.end_time.isoformat(), '2026-09-16T21:00:00+03:00')

    def test_only_full_window_cancels_events_and_polls(self):
        start = as_local(datetime(2026, 9, 16))
        e = CalendarEvent(google_event_id='missing', start_time=start + timedelta(days=1))
        outside = CalendarEvent(google_event_id='outside', start_time=start + timedelta(days=100))
        self.db.add_all([e, outside]); self.db.commit()
        poll = Poll(calendar_event_id=e.id)
        self.db.add(poll); self.db.commit()
        CalendarService(self.db).sync_from_google([])
        self.assertFalse(e.is_cancelled)
        gc = SimpleNamespace(sync_window=(start, start + timedelta(days=90)))
        CalendarService(self.db, gc).sync_from_google([])
        self.db.refresh(poll)
        self.assertTrue(e.is_cancelled)
        self.assertFalse(outside.is_cancelled)
        self.assertFalse(poll.is_active)

    def test_reconciliation_preserves_ids_and_duplicate_count(self):
        data = dict(project='Театр', date='2026-09-14', amount=5000, what='Клининг', who='Actor', expense_type='Личные траты', comment='')
        reconcile(self.db, ExpenseLog, [data, data]); self.db.commit()
        ids = [r.id for r in self.db.query(ExpenseLog).all()]
        reconcile(self.db, ExpenseLog, [data, data]); self.db.commit()
        self.assertEqual(ids, [r.id for r in self.db.query(ExpenseLog).all()])
        reconcile(self.db, ExpenseLog, [data]); self.db.commit()
        self.assertEqual(self.db.query(ExpenseLog).count(), 1)

    def test_delete_requires_current_fingerprint_and_confirmed_sheet_delete(self):
        row = ExpenseLog(date='2026-09-14', what='same', amount=100, project='Театр')
        self.db.add(row); self.db.commit()
        client = MagicMock()
        with patch('finance_router._get_client', return_value=client):
            with self.assertRaises(HTTPException):
                delete_transaction('expense', row.id, 'stale', self.db)
            client.delete_expense_row.assert_not_called()
            for outcome in (False, RuntimeError('timeout')):
                client.delete_expense_row.side_effect = outcome if isinstance(outcome, Exception) else None
                client.delete_expense_row.return_value = outcome
                with self.assertRaises(HTTPException):
                    delete_transaction('expense', row.id, fingerprint(row), self.db)
                self.assertEqual(self.db.query(ExpenseLog).count(), 1)

    def test_invalid_expense_never_writes_to_sheets(self):
        for amount, date in [('nan', '14.09.2026'), ('-1', '14.09.2026'), ('500', '31.02.2026')]:
            with patch('finance_router._get_client') as client:
                with self.assertRaises(HTTPException):
                    add_expense(ExpenseRequest(project='Театр', amount=amount, what='x', expense_type='Личные траты', date=date), self.db)
                client.assert_not_called()

    def test_sheet_delete_matches_all_fields_and_rejects_identical_rows(self):
        client = SheetsClient.__new__(SheetsClient)
        client.api = MagicMock(); client.spreadsheet_id = 'test'
        client._find_table_header_row = MagicMock(return_value=2)
        client._get_sheet_id = MagicMock(return_value=7)
        client._delete_range_row = MagicMock()
        expected = dict(project='Театр', date='14.09.2026', who='Actor', amount=5000, what='same', expense_type='Личные траты', comment='')
        first = ['Театр','14.09.2026','Actor','100','same','Личные траты','']
        correct = ['Театр','14.09.2026','Actor','5 000,00','same','Личные траты','']
        client.api.values.return_value.get.return_value.execute.return_value = {'values': [first, correct]}
        self.assertTrue(client.delete_expense_row(expected))
        self.assertEqual(client._delete_range_row.call_args.args, (7, 3))
        client._delete_range_row.reset_mock()
        client.api.values.return_value.get.return_value.execute.return_value = {'values': [correct, correct]}
        with self.assertRaises(ValueError):
            client.delete_expense_row(expected)
        client._delete_range_row.assert_not_called()


class AppLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_all_tasks_and_closes_bot(self):
        import asyncio
        import main
        tasks = [asyncio.create_task(asyncio.sleep(100)) for _ in range(4)]
        main.app.state.tasks = tasks
        with patch.object(main.bot.session, 'close', AsyncMock()) as close:
            await main.shutdown()
            close.assert_awaited_once()
        self.assertTrue(all(task.cancelled() for task in tasks))

    def test_all_api_routes_require_signed_telegram_identity(self):
        import main
        from fastapi.testclient import TestClient
        import re
        client = TestClient(main.app)
        for route in main.app.routes:
            if not route.path.startswith('/api/'):
                continue
            path = re.sub(r'\{[^}]+\}', '1', route.path)
            method = next(iter(route.methods))
            with self.subTest(path=path, method=method):
                response = client.request(method, path)
                self.assertEqual(response.status_code, 401)

    async def test_partial_campaign_keeps_sent_poll_mapping(self):
        from modules.availability.router import create_campaign, CreateCampaignRequest
        from modules.availability.models import AvailabilityPoll, AvailabilityCampaign
        from sqlalchemy.pool import StaticPool
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            for n in range(10):
                db.add(CalendarEvent(title='Test', start_time=as_local(datetime(2026, 10, n + 1, 19)), end_time=as_local(datetime(2026, 10, n + 1, 21))))
            db.commit()
            ids = [e.id for e in db.query(CalendarEvent).all()]
            msg = SimpleNamespace(poll=SimpleNamespace(id='tg-test'), message_id=123)
            with patch('modules.availability.router.GROUP_CHAT_ID', -100123), patch('modules.availability.router._ensure_campaign_columns'), patch('bot.bot.send_poll', AsyncMock(side_effect=[msg, RuntimeError('timeout')])) as send:
                with self.assertRaises(HTTPException):
                    await create_campaign(CreateCampaignRequest(event_ids=ids, show_names=['Test']), db)
                sent = db.query(AvailabilityPoll).one()
                self.assertEqual(sent.telegram_poll_id, 'tg-test')
                self.assertEqual(len(sent.options), 9)
                self.assertEqual(send.call_args_list[0].kwargs['options'][-1], 'Ни одна из дат')
        engine.dispose()
