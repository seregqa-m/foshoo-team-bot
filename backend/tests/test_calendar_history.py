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

    def test_october_11_alias_is_classified_in_calendar_api(self):
        from modules.theater.models import TheaterShow
        show = TheaterShow(name='Любовь Громова', normalized_name='любовь громова')
        self.db.add(show)
        self.db.add(CalendarEvent(title='ЛГ[Спект]', start_time=datetime(2026, 10, 11, 19),
                                  end_time=datetime(2026, 10, 11, 21)))
        self.db.commit()
        with patch('modules.calendar.services.local_now', return_value=as_local(datetime(2026, 10, 2))):
            event = get_events(days=60, db=self.db)['events'][0]
        self.assertEqual(event['title'], 'ЛГ[Спект]')
        self.assertEqual(event['event_type'], 'performance')
        self.assertEqual(event['show_name'], 'Любовь Громова')
        self.assertEqual(event['show_id'], show.id)

    def test_calendar_uses_stable_catalog_identity_for_aliases_and_manual_selection(self):
        from modules.theater.models import TheaterShow, TheaterShowAlias
        show = TheaterShow(name='Цианистый Калий', normalized_name='цианистый калий')
        other = TheaterShow(name='Урод', normalized_name='урод')
        self.db.add_all([show, other])
        self.db.flush()
        self.db.add(TheaterShowAlias(normalized_name='калий', show_id=show.id))
        titles = ['Репетиция [Цианистый Калий]', 'Калий [Реп]', 'Цианистый Калий',
                  'Разбор [Реп]', 'Калий и Урод [Реп]', 'Труппа 1', 'Труппа 2']
        for title in titles:
            self.db.add(CalendarEvent(title=title, start_time=datetime(2026, 10, 7, 19),
                end_time=datetime(2026, 10, 7, 21),
                poll_show_id=show.id if title == 'Разбор [Реп]' else None,
                poll_show_title=title if title == 'Разбор [Реп]' else None))
        self.db.commit()
        with patch('modules.calendar.services.local_now', return_value=as_local(datetime(2026, 10, 6))):
            events = {e['title']: e for e in get_events(db=self.db)['events']}
        for title in titles[:4]:
            self.assertEqual(events[title]['show_id'], show.id)
            self.assertEqual(events[title]['show_name'], show.name)
        self.assertEqual(events[titles[2]]['event_type'], 'performance')
        self.assertIsNone(events[titles[4]]['show_id'])  # Ambiguous: no arbitrary color or chat.
        for title in titles[-2:]:
            self.assertIsNone(events[title]['event_type'])
            self.assertIsNone(events[title]['show_id'])

    def test_schedule_column_resolves_alias_but_does_not_assign_rehearsal(self):
        from sheets_client import SheetsClient, SCHEDULE_SHEET
        client = SheetsClient.__new__(SheetsClient)
        client.api = MagicMock()
        client.spreadsheet_id = 'test'
        client.api.values.return_value.get.return_value.execute.return_value = {'values': [['Актёр']]}
        client.api.get.return_value.execute.return_value = {'sheets': [{'properties': {
            'title': SCHEDULE_SHEET, 'sheetId': 0, 'gridProperties': {'columnCount': 10},
        }}]}
        with patch.object(client, 'get_show_names', return_value=['Любовь Громова']):
            count = client.ensure_schedule_columns([
                (datetime(2026, 10, 11, 19), 'ЛГ[Спект]'),
                (datetime(2026, 10, 12, 19), 'ЛГ[Реп]'),
                (datetime(2026, 10, 13, 19), 'Репетиция [Любовь Громова]'),
            ])
        self.assertEqual(count, 3)
        values = client.api.values.return_value.update.call_args.kwargs['body']['values']
        self.assertEqual(values[1], ['ЛЮБОВЬ ГРОМОВА', '', ''])
