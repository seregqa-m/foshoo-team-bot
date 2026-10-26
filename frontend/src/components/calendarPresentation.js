export const PERFORMANCE_COLOR = '#6EE7B7';
export const OTHER_COLOR = '#D1D5DB';

export function getEventGroup(event) {
  if (event.event_type === 'performance') return 'shows';
  if (event.event_type === 'rehearsal' && event.show_id) return `show:${event.show_id}`;
  if (event.color_group_id) return `color:${event.color_group_id}`;
  return 'other';
}

export function getEventColor(event) {
  if (event.event_type === 'performance') return PERFORMANCE_COLOR;
  // Stable catalog IDs keep colors through renames, aliases and date changes.
  // Space consecutive IDs across the wheel, reserving greens for performances.
  if (event.event_type === 'rehearsal' && event.show_id) {
    const hue = ((Number(event.show_id) * 103.1308) % 270 + 180) % 360;
    return `hsl(${hue.toFixed(2)}, 65%, 78%)`;
  }
  // Only server-confirmed recurring groups receive a pale decorative color.
  // This identity never determines a show's chat or enables a poll.
  if (!event.color_group_id) return OTHER_COLOR;
  const hue = ((Number(event.color_group_id) * 103.1308) % 270 + 180) % 360;
  return `hsl(${hue.toFixed(2)}, 55%, 89%)`;
}

export function calendarFilters(events) {
  const shows = new Map();
  const recurring = new Map();
  for (const event of events) {
    if (event.event_type === 'rehearsal' && event.show_id) {
      shows.set(event.show_id, { key: getEventGroup(event), label: event.show_name,
        color: getEventColor(event) });
    } else if (event.event_type !== 'performance' && event.color_group_id) {
      recurring.set(event.color_group_id, { key: getEventGroup(event), label: event.color_group_name,
        color: getEventColor(event) });
    }
  }
  return [
    { key: 'all', label: 'Все', color: '#E5E7EB' },
    { key: 'rehearsals', label: 'Репетиции', color: '#DDD6FE' },
    { key: 'shows', label: 'Спектакли', color: PERFORMANCE_COLOR },
    ...[...shows.values()].sort((a, b) => a.label.localeCompare(b.label, 'ru')),
    ...[...recurring.values()].sort((a, b) => a.label.localeCompare(b.label, 'ru')),
    { key: 'other', label: 'Прочее', color: OTHER_COLOR },
  ];
}

export function matchesCalendarFilter(event, filter) {
  return filter === 'all' || (filter === 'rehearsals'
    ? event.event_type === 'rehearsal' : getEventGroup(event) === filter);
}
