import { calendarFilters, getEventColor, matchesCalendarFilter, PERFORMANCE_COLOR, OTHER_COLOR } from './calendarPresentation';

test('catalog identity keeps rehearsal colors stable across aliases, renames and filtering', () => {
  const a = { show_id: 1, show_name: 'Калий', event_type: 'rehearsal', title: 'Калий [Реп]' };
  const renamed = { ...a, show_name: 'Цианистый Калий', title: 'Репетиция [Цианистый Калий]' };
  const b = { show_id: 2, show_name: 'Урод', event_type: 'rehearsal' };
  expect(getEventColor(a)).toBe(getEventColor(renamed));
  expect(getEventColor(a)).not.toBe(getEventColor(b));
  const filter = list => calendarFilters(list).find(f => f.key === 'show:1');
  expect(filter([a, b]).color).toBe(filter([b, renamed]).color);
  expect(filter([renamed]).color).toBe(filter([a, b]).color);
  expect(filter([renamed]).label).toBe('Цианистый Калий');
  expect(matchesCalendarFilter(renamed, 'show:1')).toBe(true);
  expect(matchesCalendarFilter(b, 'show:1')).toBe(false);
  expect(matchesCalendarFilter({ ...a, event_type: 'performance' }, 'show:1')).toBe(false);
});

test('performance and catalog rehearsal rules take priority over decorative grouping', () => {
  for (const show_id of [1, 2, 10, 37, null]) {
    expect(getEventColor({ event_type: 'performance', show_id, color_group_id: 20 })).toBe(PERFORMANCE_COLOR);
  }
  const rehearsal = { event_type: 'rehearsal', show_id: 1 };
  expect(getEventColor({ ...rehearsal, color_group_id: 20 })).toBe(getEventColor(rehearsal));
});

test('rare events, rental and cleaning remain in gray Other without title-based guessing', () => {
  for (const title of ['Лаба Игошиной', 'Уборка', 'Аренда Денис', 'мк Шульгин', 'Разовая встреча']) {
    const event = { title };
    expect(getEventColor(event)).toBe(OTHER_COLOR);
    expect(matchesCalendarFilter(event, 'other')).toBe(true);
    expect(matchesCalendarFilter(event, 'rehearsals')).toBe(false);
  }
  expect(calendarFilters([]).find(f => f.key === 'other').color).toBe(OTHER_COLOR);
});

test('recurring groups share a pale color and filter without granting poll eligibility', () => {
  const a = { title: 'Фрекен Жули', color_group_id: 7, color_group_name: 'Фрекен Жули' };
  const b = { ...a, title: 'Фрекен Жюли' };
  const lab = { title: 'Лаба Игошиной', color_group_id: 8, color_group_name: 'Лаба Игошиной' };
  expect(getEventColor(a)).toBe(getEventColor(b));
  expect(getEventColor(a)).not.toBe(getEventColor(lab));
  expect(getEventColor(a)).toMatch(/55%, 89%/);
  expect(getEventColor({ event_type: 'rehearsal', show_id: 7 })).toMatch(/65%, 78%/);
  const filters = calendarFilters([a, b, lab]);
  expect(filters.filter(f => f.key === 'color:7')).toHaveLength(1);
  expect(filters.find(f => f.key === 'color:7').color).toBe(getEventColor(a));
  expect(matchesCalendarFilter(b, 'color:7')).toBe(true);
  expect(matchesCalendarFilter(b, 'other')).toBe(false);
  expect(matchesCalendarFilter(b, 'rehearsals')).toBe(false);
  expect(getEventColor({ ...a, title: 'Другое написание' })).toBe(getEventColor(a));
});
