import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://',
                             'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    import main
    from bot import _prepare_campaign
    from core.database import Base
    from core.time import as_local
    from modules.calendar.models import CalendarEvent
    from modules.polling.models import Poll, PollVote
    from modules.notifications.models import NotificationSetting
    from modules.notifications.router import UpdateSettingsRequest, get_notification_settings, update_notification_settings
    from modules.assistant.context import _collect_settings
    from modules.assistant.tools import _update_settings_handler

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class ShowSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(NotificationSetting(user_id=42, current_show='Старый спектакль',
                                        poll_reminders_enabled=True, reminder_time='00:00'))
        self.db.commit()
        for target, value in [('config.ADMIN_ID', 42), ('config.GROUP_CHAT_ID', -1001),
                              ('modules.notifications.router.ADMIN_ID', 42),
                              ('modules.assistant.context.ADMIN_ID', 42)]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_legacy_choice_is_absent_from_settings_and_cannot_be_updated(self):
        self.assertNotIn('current_show', await get_notification_settings(user_id=42, db=self.db))
        self.assertNotIn('current_show', _collect_settings(self.db))
        # Old clients can still save other settings, but cannot revive the selector.
        await update_notification_settings(UpdateSettingsRequest(
            current_show='Новый спектакль', reminder_time='17:30'), user_id=42, db=self.db)
        settings = self.db.query(NotificationSetting).one()
        self.assertEqual(settings.reminder_time, '17:30')
        self.assertEqual(settings.current_show, 'Старый спектакль')
        with self.assertRaises(HTTPException) as error:
            await _update_settings_handler(self.db, {'current_show': 'Новый спектакль'}, {})
        self.assertEqual(error.exception.status_code, 400)

    async def test_reminders_use_each_events_cast_and_ignore_the_legacy_choice(self):
        for index, title in enumerate(['ЛГ[Реп]', 'Урод[Реп]', 'Труппа 1']):
            event = CalendarEvent(title=title, start_time=datetime(2026, 10, 5, 18 + index))
            self.db.add(event)
            self.db.flush()
            poll = Poll(calendar_event_id=event.id, telegram_message_id=100 + index)
            self.db.add(poll)
            self.db.flush()
            if index == 0:
                self.db.add(PollVote(poll_id=poll.id, user_id=84, username='voted', answer='yes'))
        self.db.commit()
        with patch('main.SessionLocal', self.Session), \
             patch('main.local_now', return_value=as_local(datetime(2026, 10, 4, 19))), \
             patch('main.GOOGLE_CALENDAR_JSON', __file__), patch('config.GOOGLE_SHEETS_ID', 'test'), \
             patch('sheets_client.SheetsClient') as sheets, \
             patch.object(main.bot, 'send_message', AsyncMock()) as send, \
             patch.object(main.bot, 'pin_chat_message', AsyncMock()):
            sheets.return_value.get_show_names.return_value = ['Любовь Громова', 'Урод']
            sheets.return_value.get_actor_mapping.return_value = {
                'gromova': 'Аня', 'urod': 'Борис', 'both': 'Вера', 'voted': 'Глеб'}
            sheets.return_value.get_show_cast.side_effect = lambda name: {
                'Любовь Громова': ['Аня', 'Вера', 'Глеб'], 'Урод': ['Борис', 'Вера']}[name]
            await main._send_poll_reminders()
        self.assertEqual(send.await_count, 3)
        texts = {call.kwargs['text'].rsplit('/', 1)[-1]: call.kwargs['text'] for call in send.await_args_list}
        self.assertIn('@gromova', texts['100'])
        self.assertNotIn('@urod', texts['100'])
        self.assertNotIn('@voted', texts['100'])
        self.assertIn('@urod', texts['101'])
        self.assertNotIn('@gromova', texts['101'])
        for username in ['gromova', 'urod', 'voted', 'both']:
            self.assertIn('@' + username, texts['102'])
        self.assertTrue(all(call.kwargs['chat_id'] == -1001 for call in send.await_args_list))

    def test_monthly_campaign_is_not_limited_by_the_legacy_choice(self):
        with patch('core.database.SessionLocal', self.Session), patch('sheets_client.SheetsClient') as sheets:
            sheets.return_value.get_show_names.return_value = ['Урод', 'Любовь Громова']
            campaign = _prepare_campaign(2026, 10)
        self.assertEqual(campaign.show_names, ['Урод', 'Любовь Громова'])
