import unittest

from modules.calendar.classification import classify_event, is_rehearsal


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
            ('Спектакль не указан', 'performance', None),
            ('Труппа 1 [зал]', None, None),
            ('', None, None),
        ]:
            with self.subTest(title=title):
                self.assertEqual(classify_event(title, ['Гамлет', 'Урод', '']),
                                 {'event_type': event_type, 'show_name': show_name})

    def test_alias_uses_canonical_spelling_from_catalog(self):
        self.assertEqual(classify_event('ЛГ[Спект]', ['Любовь громова'])['show_name'], 'Любовь громова')

    def test_type_words_and_bracketed_show_names(self):
        for title, expected_type, expected_show in [
            ('Репетиция [Цианистый Калий]', 'rehearsal', 'Цианистый Калий'),
            ('РЕП. [ цианистый   калий ]', 'rehearsal', 'Цианистый Калий'),
            ('Репетиция (Цианистый Калий)', 'rehearsal', 'Цианистый Калий'),
            ('Цианистый Калий [Реп]', 'rehearsal', 'Цианистый Калий'),
            ('Репетиция «Цианистый Калий»', 'rehearsal', 'Цианистый Калий'),
            ('Спект [Цианистый Калий]', 'performance', 'Цианистый Калий'),
            ('Спектакль [Цианистый Калий]', 'performance', 'Цианистый Калий'),
            ('МИКРОПОЛЬ', 'performance', 'МИКРОПОЛЬ'),
            ('Цианистый Калий', 'performance', 'Цианистый Калий'),
            ('Репетиция [ЛГ]', 'rehearsal', 'Любовь Громова'),
            ('Репертуар [МИКРОПОЛЬ]', 'performance', 'МИКРОПОЛЬ'),
            ('Инспектор', None, None),
            ('Репетиция [Новый спектакль]', 'rehearsal', 'Новый спектакль'),
            ('[Новый спектакль]', 'performance', 'Новый спектакль'),
        ]:
            with self.subTest(title=title):
                self.assertEqual(classify_event(title, ['Цианистый Калий', 'МИКРОПОЛЬ', 'Новый спектакль']),
                                 {'event_type': expected_type, 'show_name': expected_show})

    def test_attendance_respects_explicit_type_even_without_catalog(self):
        for title, expected in [
            ('Труппа 1 — премьера [Спект]', False),
            ('Труппа 1 — ЛГ', False),
            ('ЛГ[Реп]', True),
            ('Труппа 1 — Гамлет[Реп]', True),
            ('Труппа 1', False),
            ('Труппа 2 — ЛГ[Реп]', True),
            ('Лаба — ЛГ[Реп]', True),
            ('Репетиция [Гамлет]', True),
            ('Реп. [Гамлет]', True),
            ('Спектакль [Гамлет]', False),
            ('Гамлет', False),
            ('Труппа 2 — Репетиция [Гамлет]', True),
            ('Лаба — Репетиция [Гамлет]', True),
        ]:
            with self.subTest(title=title):
                self.assertEqual(is_rehearsal(title, ['Гамлет']), expected)
