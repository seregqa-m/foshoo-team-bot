import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

with patch.dict(os.environ, {"BOT_TOKEN": "123456:offline-test-token", "DATABASE_URL": "sqlite://"}, clear=True), patch("dotenv.load_dotenv"):
    from core.database import Base
    from core.time import as_local
    from modules.calendar.models import CalendarEvent
    from modules.calendar.google_client import GoogleCalendarClient
    from modules.calendar.router import get_events
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class CalendarHistoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_calendar_history_includes_past_and_ongoing_but_not_cancelled(self):
        now = as_local(datetime(2026, 10, 1, 15))
        for title, start, end, cancelled in [
            ('past', now - timedelta(days=400), now - timedelta(days=399), False),
            ('ongoing', now - timedelta(hours=1), now + timedelta(hours=1), False),
            ('future', now + timedelta(days=1), now + timedelta(days=2), False),
            ('cancelled', now - timedelta(days=1), now, True),
            ('outside', now + timedelta(days=61), now + timedelta(days=62), False),
        ]:
            self.db.add(CalendarEvent(title=title, start_time=start, end_time=end, is_cancelled=cancelled))
        self.db.commit()
        with patch('modules.calendar.services.local_now', return_value=now):
            history = get_events(days=60, db=self.db, include_past=True)['events']
            upcoming = get_events(days=60, db=self.db)['events']
        self.assertEqual([e['title'] for e in history], ['past', 'ongoing', 'future'])
        self.assertEqual([e['title'] for e in upcoming], ['future'])

    def test_google_history_uses_same_window_for_all_pages_and_cancellations(self):
        client = GoogleCalendarClient.__new__(GoogleCalendarClient)
        client.service = MagicMock()
        request = client.service.events.return_value.list
        request.return_value.execute.side_effect = [
            {'items': [{'id': 'past'}], 'nextPageToken': 'page2'},
            {'items': [{'id': 'future'}]},
        ]
        self.assertEqual(client.get_events('test'), [{'id': 'past'}, {'id': 'future'}])
        start, end = client.sync_window
        self.assertEqual(end - start, timedelta(days=455))
        self.assertEqual(request.call_args_list[1].kwargs['pageToken'], 'page2')
        for call in request.call_args_list:
            self.assertEqual(call.kwargs['timeMin'], start.isoformat())
            self.assertEqual(call.kwargs['timeMax'], end.isoformat())
