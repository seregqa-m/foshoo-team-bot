import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

with patch.dict(os.environ, {"BOT_TOKEN": "123456:offline-test-token", "DATABASE_URL": "sqlite://", "GOOGLE_CALENDAR_JSON": "/missing"}, clear=True), patch("dotenv.load_dotenv"):
    from core.database import Base
    from modules.calendar.models import CalendarEvent
    from modules.availability.models import AvailabilityPoll, AvailabilityPollOption
    from modules.availability.router import CreateCampaignRequest, create_campaign, _campaign_dates, check_dates
    from bot import _handle_availability_answer

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker


class AvailabilityDateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_manual_dates_are_sorted_deduplicated_and_persisted_without_events(self):
        req = CreateCampaignRequest(show_names=['Урод'], dates=['2026-10-10', '2026-10-07', '2026-10-07'])
        send = AsyncMock(return_value=SimpleNamespace(poll=SimpleNamespace(id='test'), message_id=1))
        with patch('modules.availability.router.GROUP_CHAT_ID', -1001), patch('bot.bot.send_poll', send), patch('modules.availability.router._ensure_campaign_columns') as columns:
            result = await create_campaign(req, self.db)
        self.assertEqual(result['events_count'], 2)
        self.assertEqual(self.db.query(CalendarEvent).count(), 0)
        options = self.db.query(AvailabilityPollOption).order_by(AvailabilityPollOption.option_index).all()
        self.assertEqual([o.selected_date for o in options], [date(2026, 10, 7), date(2026, 10, 10)])
        self.assertTrue(all(o.calendar_event_id is None for o in options))
        self.assertEqual(send.call_args.kwargs['options'][-1], 'Ни одна из дат')
        self.assertEqual([dt.date() for dt, _ in columns.call_args.args[0]], [date(2026, 10, 7), date(2026, 10, 10)])

    async def test_full_month_splits_into_polls_without_losing_dates(self):
        req = CreateCampaignRequest(show_names=['Урод'], dates=[date(2026, 10, n) for n in range(1, 32)])
        send = AsyncMock(side_effect=[SimpleNamespace(poll=SimpleNamespace(id=str(n)), message_id=n) for n in range(4)])
        with patch('modules.availability.router.GROUP_CHAT_ID', -1001), patch('bot.bot.send_poll', send), patch('modules.availability.router._ensure_campaign_columns'):
            result = await create_campaign(req, self.db)
        self.assertEqual(result['polls_count'], 4)
        self.assertEqual(self.db.query(AvailabilityPollOption).count(), 31)
        self.assertEqual([len(c.kwargs['options']) for c in send.call_args_list], [10, 10, 10, 5])

    def test_invalid_selection_is_rejected(self):
        for payload in [{'dates': []}, {'dates': ['2026-10-01', '2026-11-01']}, {'dates': ['2026-10-01'], 'event_ids': [1]}]:
            with self.assertRaises(HTTPException):
                _campaign_dates(CreateCampaignRequest(show_names=['Урод'], **payload), self.db)
        with self.assertRaises(ValidationError):
            CreateCampaignRequest(show_names=['Урод'], dates=['2026-02-30'])

    def test_legacy_events_are_still_supported_and_same_day_is_one_option(self):
        events = [CalendarEvent(title='Труппа 1', start_time=datetime(2026, 10, 3, hour)) for hour in (12, 19)]
        self.db.add_all(events); self.db.commit()
        selected = _campaign_dates(CreateCampaignRequest(show_names=['Урод'], event_ids=[e.id for e in events]), self.db)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][0], date(2026, 10, 3))

    def test_votes_for_manual_dates_reach_sheets_including_retraction(self):
        poll = AvailabilityPoll()
        self.db.add(poll); self.db.flush()
        self.db.add_all([AvailabilityPollOption(poll_id=poll.id, option_index=n, selected_date=date(2026, 10, n+1)) for n in (0, 1)])
        self.db.commit()
        sheets = MagicMock()
        with patch('config.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), patch('sheets_client.SheetsClient', return_value=sheets):
            for selected, expected in [([0], ['yes', 'no']), ([2], ['no', 'no']), ([], ['retracted', 'retracted'])]:
                sheets.reset_mock()
                _handle_availability_answer(SimpleNamespace(user=SimpleNamespace(id=42, username='actor'), option_ids=selected), poll, self.db)
                self.assertEqual([c.args[2] for c in sheets.record_poll_answer.call_args_list], expected)
                self.assertEqual([c.args[1].date() for c in sheets.record_poll_answer.call_args_list], [date(2026, 10, 1), date(2026, 10, 2)])

    def test_date_check_includes_manual_dates(self):
        sheets = MagicMock()
        sheets.check_dates_exist.return_value = [datetime(2026, 10, 7)]
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), patch('sheets_client.SheetsClient', return_value=sheets):
            result = check_dates(dates='2026-10-07', db=self.db)
        self.assertFalse(result['all_ok'])
        sheets.check_dates_exist.assert_called_once_with([datetime(2026, 10, 7)])

    def test_existing_database_migration_preserves_options_and_is_repeatable(self):
        from main import run_migrations
        with self.engine.begin() as conn:
            conn.execute(text('ALTER TABLE availability_poll_options DROP COLUMN selected_date'))
            conn.execute(text("INSERT INTO availability_poll_options (id, option_index, calendar_event_id) VALUES (1, 0, 99)"))
        with patch('main.engine', self.engine):
            run_migrations()
            run_migrations()
        self.assertIn('selected_date', {c['name'] for c in inspect(self.engine).get_columns('availability_poll_options')})
        option = self.db.get(AvailabilityPollOption, 1)
        self.assertEqual(option.calendar_event_id, 99)
        self.assertIsNone(option.selected_date)
