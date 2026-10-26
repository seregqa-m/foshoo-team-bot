import { calendarFilters, calendarDetails, getEventDetailKey, getEventColor, matchesCalendarFilter, PERFORMANCE_COLOR, OTHER_COLOR } from './calendarPresentation';

test('catalog identity keeps rehearsal colors and detail selection stable across renames', () => {
  const a = { show_id: 1, show_name: 'Калий', event_type: 'rehearsal' };
  const renamed = { ...a, show_name: 'Цианистый Калий' };
  const b = { show_id: 2, show_name: 'Урод', event_type: 'rehearsal' };
  expect(getEventColor(a)).toBe(getEventColor(renamed));
  expect(getEventColor(a)).not.toBe(getEventColor(b));
  expect(getEventDetailKey(a)).toBe(getEventDetailKey(renamed));
  expect(calendarDetails([renamed, b, renamed]).find(f => f.key === 'show:1'))
    .toEqual({ key: 'show:1', label: 'Цианистый Калий', count: 2 });
});

test('only nonempty primary types appear; recurring names are secondary choices', () => {
  const events = [{ title: 'Лаба', color_group_id: 7, color_group_name: 'Лаба' }, { title: 'Уборка' }];
  expect(calendarFilters(events).map(f => f.key)).toEqual(['all', 'other']);
  expect(calendarFilters([]).map(f => f.key)).toEqual(['all']);
  expect(calendarDetails(events).map(f => f.key)).toEqual(['color:7', 'other']);
  expect(events.every(e => matchesCalendarFilter(e, 'other'))).toBe(true);
  expect(matchesCalendarFilter({ event_type: 'rehearsal', color_group_id: 7 }, 'other')).toBe(false);
});

test('external performances need neither a chat nor a catalog entry', () => {
  const external = { event_type: 'performance', title: 'Фрекен Жюли [Спект]' };
  expect(matchesCalendarFilter(external, 'shows')).toBe(true);
  expect(matchesCalendarFilter(external, 'rehearsals')).toBe(false);
  expect(getEventColor(external)).toBe(PERFORMANCE_COLOR);
  expect(calendarDetails([external, external])[0]).toEqual({
    key: 'title:Фрекен Жюли [Спект]', label: 'Фрекен Жюли [Спект]', count: 2,
  });
});

test('recurring groups have equal saturation to rehearsals; explicit types retain priority', () => {
  const recurring = { color_group_id: 7, title: 'Фрекен Жули' };
  expect(getEventColor(recurring)).toBe(getEventColor({ ...recurring, title: 'Фрекен Жюли' }));
  expect(getEventColor(recurring)).toMatch(/65%, 70%/);
  expect(getEventColor({ event_type: 'rehearsal', show_id: 1 })).toMatch(/65%, 70%/);
  expect(getEventColor({ ...recurring, event_type: 'performance' })).toBe(PERFORMANCE_COLOR);
  expect(getEventColor({ ...recurring, event_type: 'rehearsal', show_id: 1 }))
    .toBe(getEventColor({ event_type: 'rehearsal', show_id: 1 }));
  expect(getEventColor({ title: 'Уборка' })).toBe(OTHER_COLOR);
});
