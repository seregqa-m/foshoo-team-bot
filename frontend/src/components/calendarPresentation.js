export const PERFORMANCE_COLOR = '#52C99A';
export const OTHER_COLOR = '#B5BDC9';

export function getEventGroup(event) {
  if (event.event_type === 'performance') return 'shows';
  if (event.event_type === 'rehearsal' && event.show_id) return `show:${event.show_id}`;
  if (event.color_group_id) return `color:${event.color_group_id}`;
  return 'other';
}

export function getEventColor(event) {
  if (event.event_type === 'performance') return PERFORMANCE_COLOR;
  // Stable IDs keep colors through renames, aliases and date changes.
  const isCatalogRehearsal = event.event_type === 'rehearsal' && !!event.show_id;
  const id = isCatalogRehearsal ? event.show_id : event.color_group_id;
  if (!id) return OTHER_COLOR;
  // These IDs come from independent tables. Interleave their namespaces:
  // show:N -> 2N-1, color:N -> 2N. No titles or visible-event ordering involved.
  const colorIndex = Number(id) * 2 - (isCatalogRehearsal ? 1 : 0);
  const hue = ((colorIndex * 103.1308) % 270 + 180) % 360;
  // Recurring groups and catalog shows have equal visual weight.
  return `hsl(${hue.toFixed(2)}, 65%, 70%)`;
}

export function matchesCalendarFilter(event, filter) {
  if (filter === 'all') return true;
  if (filter === 'rehearsals') return event.event_type === 'rehearsal';
  if (filter === 'shows') return event.event_type === 'performance';
  if (filter === 'other') return !['rehearsal', 'performance'].includes(event.event_type);
  return getEventGroup(event) === filter;
}

// Call with the same ongoing/upcoming events that can appear in the list.
export function calendarFilters(events) {
  return [
    { key: 'all', label: 'Все' },
    { key: 'rehearsals', label: 'Репетиции' },
    { key: 'shows', label: 'Спектакли' },
    { key: 'other', label: 'Прочее' },
  ].filter(filter => filter.key === 'all' || events.some(event => matchesCalendarFilter(event, filter.key)));
}

export function getEventDetailKey(event) {
  if (event.event_type === 'performance') {
    return event.show_id ? `performance:${event.show_id}` : `title:${event.show_name || event.title}`;
  }
  return getEventGroup(event);
}

export function calendarDetails(events) {
  const groups = new Map();
  for (const event of events) {
    const key = getEventDetailKey(event);
    if (!groups.has(key)) groups.set(key, {
      key,
      label: event.event_type === 'performance' ? (event.show_name || event.title)
        : event.event_type === 'rehearsal' && event.show_id ? event.show_name
          : event.color_group_name || 'Остальные события',
      count: 0,
    });
    groups.get(key).count += 1;
  }
  return [...groups.values()].sort((a, b) => a.label.localeCompare(b.label, 'ru'));
}
