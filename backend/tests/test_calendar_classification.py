import unittest

from modules.calendar.classification import classify_event, is_troupe_event


class CalendarClassificationTests(unittest.TestCase):
    def test_type_and_show_are_resolved_independently(self):
        for title, event_type, show_name in [
            ('ЛГ[Спект]', 'performance', 'Любовь Громова'),
            ('лг [ СПЕКТ. ]', 'performance', 'Любовь Громова'),
            ('Любовь Громова[Реп]', 'rehearsal', 'Любовь Громова'),
            ('ЛГ[Репетиция]', 'rehearsal', 'Любовь Громова'),
            ('Премьера [Спектакль]', 'performance', None),
            ('Труппа 1 — Гамлет[Реп]', 'rehearsal', 'Гамлет'),
            ('Труппа 1 — Гамлет', 'performance', 'Гамлет'),
            ('ЛГ', 'performance', 'Любовь Громова'),
            ('Долг', None, None),
            ('ЛГБТ', None, None),
            ('Уродливый', None, None),
            ('Спектакль не указан', None, None),
            ('Труппа 1 [зал]', None, None),
            ('', None, None),
        ]:
            with self.subTest(title=title):
                self.assertEqual(classify_event(title, ['Гамлет', 'Урод', '']),
                                 {'event_type': event_type, 'show_name': show_name})

    def test_alias_uses_canonical_spelling_from_catalog(self):
        self.assertEqual(classify_event('ЛГ[Спект]', ['Любовь громова'])['show_name'], 'Любовь громова')

    def test_attendance_respects_explicit_type_even_without_catalog(self):
        for title, expected in [
            ('Труппа 1 — премьера [Спект]', False),
            ('Труппа 1 — ЛГ', False),
            ('ЛГ[Реп]', True),
            ('Труппа 1 — Гамлет[Реп]', True),
            ('Труппа 1', True),
            ('Труппа 2 — ЛГ[Реп]', False),
            ('Лаба — ЛГ[Реп]', False),
        ]:
            with self.subTest(title=title):
                self.assertEqual(is_troupe_event(title, ['Гамлет']), expected)
