import copy
import unittest
from io import BytesIO
from unittest.mock import patch

import test_repertoire_sharing  # Initialize the isolated test configuration.
from PIL import Image, ImageDraw, ImageFont
from modules.planning.repertoire_image import calendar_image, wrap, FONT, CELL, MARGIN, GAP


class RepertoireImageTests(unittest.TestCase):
    def variant(self):
        return {'count': 3, 'manual': True, 'missing': [], 'excess': [], 'spread_warnings': [], 'load_warnings': [],
                'entries': [
                    {'date': '2027-01-16', 'key': 'one', 'name': 'Урод', 'fixed': False, 'start_time': '2027-01-16T18:45:00+03:00'},
                    {'date': '2027-01-17', 'key': 'two', 'name': 'Любовь Громова', 'fixed': False, 'start_time': '2027-01-17T18:00:00+03:00'},
                    {'date': '2027-01-31', 'key': 'three', 'name': 'Цианистый Калий', 'fixed': True, 'start_time': '2027-01-31T19:00:00+03:00'}]}

    def test_manual_dates_names_and_times_are_drawn_without_mutating_variant(self):
        variant = self.variant()
        original = copy.deepcopy(variant)
        draw_text = ImageDraw.ImageDraw.text
        with patch.object(ImageDraw.ImageDraw, 'text', autospec=True, side_effect=draw_text) as drawn:
            raw = calendar_image('2027-01', variant, 3, [])
        words = [call.args[2] for call in drawn.call_args_list]
        for expected in ('16', '17', '31', '18:45', '18:00', '19:00', 'Урод', 'Любовь', 'Громова', 'Цианистый', 'Калий'):
            self.assertIn(expected, words)
        self.assertEqual(variant, original)
        self.assertEqual(raw, calendar_image('2027-01', variant, 3, []))
        variant['entries'][0]['start_time'] = '2027-01-16T20:00:00+03:00'
        self.assertNotEqual(raw, calendar_image('2027-01', variant, 3, []))

    def test_monday_first_grid_handles_a_six_week_month_and_multiple_shows(self):
        variant = self.variant()
        variant['entries'] = [{'date': '2027-05-31', 'name': name, 'fixed': True, 'start_time': None}
                              for name in ('Первый спектакль', 'Второй спектакль')]
        draw_text = ImageDraw.ImageDraw.text
        with patch.object(ImageDraw.ImageDraw, 'text', autospec=True, side_effect=draw_text) as drawn:
            image = Image.open(BytesIO(calendar_image('2027-05', variant, 2, [])))
        labels = {call.args[2]: call.args[1] for call in drawn.call_args_list}
        self.assertEqual(labels['1'][0], MARGIN + 5 * (CELL + GAP) + 12)  # Saturday
        self.assertEqual(labels['31'][0], MARGIN + 12)  # Monday, sixth week
        self.assertGreater(labels['31'][1], labels['30'][1])
        self.assertLess(max(y for _, y in labels.values()) + 30, image.height)
        self.assertLessEqual(image.width + image.height, 10000)
        self.assertIn('Первый', labels)
        self.assertIn('Второй', labels)

    def test_long_words_wrap_inside_cells_and_foreign_month_is_rejected(self):
        font = ImageFont.truetype(str(FONT), 23)
        name = 'Оченьдлинноеназваниеспектаклябезпробелов'
        lines = wrap(name, font, CELL - 24)
        self.assertEqual(''.join(lines), name)
        self.assertTrue(all(font.getlength(line) <= CELL - 24 for line in lines))
        with self.assertRaises(ValueError):
            calendar_image('2027-02', self.variant(), 3, [])
