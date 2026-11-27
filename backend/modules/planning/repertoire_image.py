"""Deterministic calendar export of the reviewed variant, independent of screen size."""
import calendar
from collections import defaultdict
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from babel.dates import format_date
from PIL import Image, ImageDraw, ImageFont

from core.time import as_local

FONT = Path(__file__).resolve().parents[2] / 'assets/fonts/DejaVuSans.ttf'
WIDTH, MARGIN, GAP = 1400, 36, 8
CELL = (WIDTH - MARGIN * 2 - GAP * 6) // 7


def wrap(text, font, width):
    """Wrap full names, including long words; never silently drop a show."""
    lines = []
    for paragraph in str(text).splitlines() or ['']:
        line = ''
        for word in paragraph.split():
            if line and font.getlength(line + ' ' + word) > width:
                lines.append(line)
                line = ''
            for char in (' ' if line else '') + word:
                if font.getlength(line + char) > width:
                    lines.append(line)
                    line = ''
                line += char
        lines.append(line)
    return lines


def calendar_image(month, variant, target, warnings):
    first = date.fromisoformat(month + '-01')
    month_label = format_date(first, 'LLLL yyyy', locale='ru_RU').capitalize()
    title_font = ImageFont.truetype(str(FONT), 44)
    font = ImageFont.truetype(str(FONT), 23)
    small = ImageFont.truetype(str(FONT), 20)
    by_day = defaultdict(list)
    for entry in sorted(variant['entries'], key=lambda e: (e['date'], e.get('start_time') or '', e['name'])):
        day = date.fromisoformat(entry['date'])
        if day.strftime('%Y-%m') != month:
            raise ValueError('В календаре есть дата другого месяца. Обновите план.')
        clock = as_local(datetime.fromisoformat(entry['start_time'])).strftime('%H:%M') if entry.get('start_time') else 'Время не задано'
        lines = wrap(clock, font, CELL - 24) + wrap(entry['name'], font, CELL - 24)
        if entry['fixed']:
            lines.extend(wrap('✓ Назначен', font, CELL - 24))
        by_day[day.day].append(lines)
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(first.year, first.month)
    heights = [max(150, max((58 + sum(len(lines) * 30 + 14 for lines in by_day[d]) for d in week), default=0)) for week in weeks]
    notes = []
    if variant.get('missing'):
        notes.append('Не хватает: ' + '; '.join(f'{s["name"]} — {s["count"]}' for s in variant['missing']))
    if variant.get('excess'):
        notes.append('Сверх плана: ' + '; '.join(f'{s["name"]} — {s["count"]}' for s in variant['excess']))
    if variant.get('spread_warnings') or variant.get('load_warnings') or warnings:
        notes.append(f'Требуют внимания: разнос — {len(variant.get("spread_warnings", []))}, '
                     f'нагрузка — {len(variant.get("load_warnings", []))}, данные — {len(warnings)}.')
    notes.append('На согласование · ' + ('Все показы уже в календаре.' if all(e['fixed'] for e in variant['entries'])
                 else 'Новые показы ещё не внесены в календарь.'))
    footer = [line for note in notes for line in wrap(note, font, WIDTH - 2 * MARGIN)]
    height = 190 + sum(heights) + GAP * len(weeks) + 30 * len(footer) + 48
    # sendPhoto limits: width+height <= 10000, ratio <= 20, file <= 10 MB.
    if WIDTH + height > 10000:
        raise ValueError('Календарь слишком большой для картинки. Сократите длинные названия спектаклей.')
    image = Image.new('RGB', (WIDTH, height), '#ffffff')
    draw = ImageDraw.Draw(image)
    draw.text((MARGIN, 26), month_label, font=title_font, fill='#292329')
    subtitle = f'Афиша на согласование · {variant["count"]} из {target} показов'
    if variant.get('manual'):
        subtitle += ' · Ручной черновик'
    draw.text((MARGIN, 88), subtitle, font=font, fill='#6c626b')
    for index, label in enumerate(('ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС')):
        draw.text((MARGIN + index * (CELL + GAP) + 12, 146), label, font=small, fill='#6c626b')
    y = 184
    for week, row_height in zip(weeks, heights):
        for column, day in enumerate(week):
            if not day:
                continue
            x = MARGIN + column * (CELL + GAP)
            active = bool(by_day[day])
            draw.rounded_rectangle((x, y, x + CELL, y + row_height), radius=12,
                                   fill='#e7f4eb' if active else '#f7f5f6', outline='#bcddc6' if active else '#e9e2e6')
            draw.text((x + 12, y + 10), str(day), font=font, fill='#205939' if active else '#6c626b')
            line_y = y + 48
            for lines in by_day[day]:
                for line in lines:
                    draw.text((x + 12, line_y), line, font=font, fill='#205939')
                    line_y += 30
                line_y += 14
        y += row_height + GAP
    for line in footer:
        draw.text((MARGIN, y + 20), line, font=font, fill='#6c626b')
        y += 30
    output = BytesIO()
    image.save(output, format='PNG', optimize=True)
    result = output.getvalue()
    if len(result) > 10_000_000:
        raise ValueError('Календарь слишком большой для отправки картинкой.')
    return result
