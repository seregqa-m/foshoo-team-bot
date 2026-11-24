import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://'}, clear=True), patch('dotenv.load_dotenv'):
    from core.database import Base
    from core.time import local_now
    from modules.calendar.models import CalendarEvent, CalendarWatchDelivery
    from modules.calendar.watcher import naming_problem, check_calendar_names
    from modules.calendar.services import CalendarService
    from modules.admin.models import SuperAdmin
    from modules.theater.models import TheaterShow
    from modules.theater.routing import show_aliases
    from modules.polling.models import Poll
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class CalendarWatcherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.db.add_all([SuperAdmin(telegram_user_id=1, granted_by=1), SuperAdmin(telegram_user_id=2, granted_by=1),
                         TheaterShow(name='Урод', normalized_name='урод'),
                         TheaterShow(name='Калий', normalized_name='калий')])
        self.db.commit()
        self.bot = AsyncMock()

    def event(self, title, **kwargs):
        now = local_now()
        event = CalendarEvent(title=title, start_time=now + timedelta(days=1),
                              end_time=now + timedelta(days=1, hours=2), **kwargs)
        self.db.add(event)
        self.db.commit()
        return event

    def test_rules_follow_existing_names_and_leave_ordinary_events_alone(self):
        aliases = show_aliases(self.db)
        for title in ('Урод [Реп]', 'Репетиция [Урод]', 'Калий (Спект)', 'Внешний [Спект]',
                      'Аренда', 'Уборка', 'Мастерская Петра', 'Урод [реп.]'):
            with self.subTest(title=title): self.assertIsNone(naming_problem(title, aliases))
        for title in ('', 'Урод', 'Неизвестный [Реп]', 'Урод и Калий [Реп]', 'Урод [Реп] [Спект]'):
            with self.subTest(title=title): self.assertIsNotNone(naming_problem(title, aliases))

    async def test_baseline_new_and_renamed_events_dedupe_survives_sessions(self):
        old_id = self.event('Урод').id
        self.assertEqual(await check_calendar_names(self.db, self.bot), 0)
        self.event('Неизвестный [Реп]', google_html_link='https://calendar.google.com/calendar/event?eid=abc')
        self.assertEqual(await check_calendar_names(self.db, self.bot), 2)
        self.assertEqual({c.args[0] for c in self.bot.send_message.call_args_list}, {1, 2})
        self.assertIn('eid=abc', self.bot.send_message.call_args.args[1])
        self.db.close()
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.assertEqual(await check_calendar_names(self.db, self.bot), 0)
        self.db.get(CalendarEvent, old_id).title = 'Калий'
        self.db.commit()
        self.assertEqual(await check_calendar_names(self.db, self.bot), 2)

    async def test_series_groups_alerts_and_html_is_escaped(self):
        await check_calendar_names(self.db, self.bot)
        for i in range(3):
            self.event('<b>Проба</b> [Реп]', recurring_event_id='series', google_event_id=f'event{i}')
        self.assertEqual(await check_calendar_names(self.db, self.bot), 2)
        text = self.bot.send_message.call_args.args[1]
        self.assertIn('&lt;b&gt;', text)
        self.assertIn('всей серии', text)

    async def test_failed_recipient_does_not_block_others_or_repeat_success(self):
        await check_calendar_names(self.db, self.bot)
        self.event('Урод')
        async def send(uid, *args, **kwargs):
            if uid == 1: raise RuntimeError('bot blocked')
        self.bot.send_message.side_effect = send
        self.assertEqual(await check_calendar_names(self.db, self.bot), 1)
        self.assertEqual(await check_calendar_names(self.db, self.bot), 0)
        delivery = self.db.query(CalendarWatchDelivery).filter_by(recipient_id=1).one()
        delivery.retry_after = datetime.utcnow() - timedelta(seconds=1)
        self.db.commit()
        self.bot.send_message.side_effect = None
        self.assertEqual(await check_calendar_names(self.db, self.bot), 1)
        self.assertEqual(self.bot.send_message.call_count, 3)

    async def test_correction_cancellation_and_revocation_stop_pending_delivery(self):
        await check_calendar_names(self.db, self.bot)
        event = self.event('Урод')
        self.bot.send_message.side_effect = RuntimeError('offline')
        await check_calendar_names(self.db, self.bot)
        event.title = 'Урод [Спект]'
        self.db.commit()
        self.bot.send_message.side_effect = None
        self.assertEqual(await check_calendar_names(self.db, self.bot), 0)
        self.event('Калий', is_cancelled=True)
        self.db.delete(self.db.get(SuperAdmin, 2))
        self.db.commit()
        self.event('Новое [Реп]')
        self.assertEqual(await check_calendar_names(self.db, self.bot), 1)
        self.assertEqual(self.bot.send_message.call_args.args[0], 1)

    def test_google_sync_preserves_all_day_link_series_and_stable_revision(self):
        source = [{'id': 'day', 'summary': 'Урод [Реп]', 'start': {'date': '2027-01-01'},
                   'end': {'date': '2027-01-02'}, 'htmlLink': 'https://calendar.google.com/calendar/event?eid=abc',
                   'recurringEventId': 'series'}]
        service = CalendarService(self.db)
        service.sync_from_google(source)
        event = self.db.query(CalendarEvent).one()
        self.assertTrue(event.is_all_day)
        self.assertEqual(event.recurring_event_id, 'series')
        stamp = event.updated_at
        service.sync_from_google(source)
        self.assertEqual(event.updated_at, stamp)
        source[0]['summary'] = 'Урод [Спект]'
        service.sync_from_google(source)
        self.assertNotEqual(event.updated_at, stamp)
