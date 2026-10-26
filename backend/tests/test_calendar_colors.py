import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://'}, clear=True), patch('dotenv.load_dotenv'):
    from core.database import Base
    from core.time import as_local
    from modules.calendar.models import CalendarEvent, CalendarColorTitle, CalendarColorGroup
    from modules.calendar.colors import color_groups, normalize_title, similar_titles
    from modules.calendar.router import get_events
    from modules.theater.models import TheaterShow
    from modules.theater.routing import show_aliases
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class CalendarColorTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.now = as_local(datetime(2026, 10, 23, 12))
        for target in ['modules.calendar.colors.local_now', 'modules.calendar.services.local_now']:
            patcher = patch(target, return_value=self.now)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def event(self, title, day=1, **kwargs):
        start = self.now + timedelta(days=day)
        row = CalendarEvent(title=title, start_time=start, end_time=start + timedelta(hours=2), **kwargs)
        self.db.add(row)
        self.db.commit()
        return row

    def groups(self):
        return color_groups(self.db, show_aliases(self.db))

    def test_normalization_typos_numbers_and_teacher_names(self):
        for a, b in [('ВДОВЫ — ??', 'Вдовы'), (' ЕЛКА! ', 'Ёлка'),
                     ('мастер-класс Розанова', 'МК Розанова'), ('Фрекен Жюли', 'Фрекен Жули')]:
            self.assertTrue(similar_titles(normalize_title(a), normalize_title(b)), (a, b))
        for a, b in [('Урод', 'Урок'), ('Вдовы', 'Вдова'), ('труппа 1', 'труппа 2'),
                     ('МК Баклакова', 'МК Баклаков'), ('МК Розанова', 'МК Шевченко'),
                     ('Интенсив Иванова', 'Интенсив Иванов')]:
            self.assertFalse(similar_titles(normalize_title(a), normalize_title(b)), (a, b))

    def test_frequency_counts_distinct_dates_and_lab_has_no_special_rule(self):
        for _ in range(3):
            self.event('Пингвины Баркова', 1)
        self.event('Лаба Игошиной', 1)
        self.assertEqual(self.groups(), {})
        for title in ['Пингвины Баркова', 'Лаба Игошиной']:
            self.event(title, 2)
            self.event(title, 3)
        groups = self.groups()
        self.assertEqual(set(groups), {'пингвины баркова', 'лаба игошиной'})
        self.assertNotEqual(groups['пингвины баркова']['color_group_id'], groups['лаба игошиной']['color_group_id'])

    def test_rental_cleaning_and_one_off_workshops_stay_gray(self):
        for title in ['Уборка', 'Генеральная уборка', 'Аренда', 'Аренда Денис', 'MUSbooking 0 booking']:
            for day in [1, 2, 3, 4]:
                self.event(title, day)
        self.event('мк Розанова', 1)
        self.event('мк Шевченко', 2)
        self.event('мк Шульгин', 3)
        self.assertEqual(self.groups(), {})

    def test_frequency_window_inclusive_boundaries_and_cancelled_events(self):
        for day in [-91, -90, 60, 61]:
            self.event('Читка', day)
        self.event('Читка', 1, is_cancelled=True)
        self.assertEqual(self.groups(), {})
        self.event('Читка', 0)
        self.assertIn('читка', self.groups())

    def test_similar_variants_share_dates_and_persist_identity_across_sessions(self):
        for title, day in [('Фрекен Жули', 1), ('Фрекен Жюли', 2), ('ФРЕКЕН ЖУЛИ!', 3)]:
            self.event(title, day)
        first = self.groups()
        identity = first['фрекен жули']['color_group_id']
        self.assertEqual(first['фрекен жюли']['color_group_id'], identity)
        self.event('Совсем другая встреча', 4)
        with self.Session() as other:
            result = color_groups(other, show_aliases(other))
            self.assertEqual(result['фрекен жюли']['color_group_id'], identity)
        self.assertEqual(self.db.query(CalendarColorTitle).count(), 3)

    def test_complete_link_prevents_chains_and_ambiguous_matches_stay_separate(self):
        # Each adjacent pair is one edit apart, but the endpoints are two edits apart.
        a, b, c = 'абвгдежзик', 'абвгдежзил', 'абвгдежзмл'
        self.event(a)
        self.groups()
        self.event(b)
        self.groups()
        self.event(c)
        self.groups()
        rows = {row.normalized_title: row.group_id for row in self.db.query(CalendarColorTitle)}
        self.assertEqual(rows[a], rows[b])
        self.assertNotEqual(rows[a], rows[c])
        # A new name within one edit of both existing groups gets its own group.
        x, y, middle = 'клмнопрсту', 'клмнопрсаф', 'клмнопрсау'
        self.event(x)
        self.groups()
        self.event(y)
        self.groups()
        identities = {self.db.get(CalendarColorTitle, title).group_id for title in [x, y]}
        self.assertEqual(len(identities), 2)
        self.event(middle)
        self.groups()
        self.assertNotIn(self.db.get(CalendarColorTitle, middle).group_id, identities)

    def test_types_destinations_and_api_range_do_not_depend_on_decorative_groups(self):
        show = TheaterShow(name='Калий', normalized_name='калий')
        self.db.add(show)
        self.db.commit()
        for day in [-2, -1, 1]:
            for title in ['Репетиция [Калий]', 'Калий', 'Лаба Игошиной']:
                self.event(title, day)
        self.event('Репетиция без спектакля', 1)
        all_events = get_events(days=60, db=self.db, include_past=True)['events']
        upcoming = get_events(days=1, db=self.db, include_past=False)['events']
        group = next(e for e in all_events if e['title'] == 'Лаба Игошиной')['color_group_id']
        self.assertIsNotNone(group)
        for event in all_events:
            if event['title'] == 'Лаба Игошиной':
                self.assertEqual(event['color_group_id'], group)
                self.assertIsNone(event['event_type'])
                self.assertIsNone(event['show_id'])
            else:
                self.assertIsNone(event['color_group_id'])
        self.assertEqual(next(e for e in upcoming if e['title'] == 'Лаба Игошиной')['color_group_id'], group)
        self.assertEqual(self.db.query(CalendarColorGroup).count(), 2)
