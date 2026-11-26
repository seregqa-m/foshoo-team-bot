import React, { useState } from 'react';

const WEEK = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const SHORT = { 'урод': 'Урод', 'любовь громова': 'ЛГ', 'цианистый калий': 'ЦК', 'микрополь': 'Микр.' };
const dayLabel = day => new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'long', weekday: 'short', timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`));

export default function RepertoireCalendar({ month, entries, pins, renderEntry }) {
  const [selectedDate, setSelectedDate] = useState(() => entries[0]?.date || `${month}-01`);
  const first = new Date(`${month}-01T12:00:00Z`);
  const offset = (first.getUTCDay() + 6) % 7;
  const last = new Date(first); last.setUTCMonth(last.getUTCMonth() + 1, 0);
  const byDate = {};
  entries.forEach(entry => { (byDate[entry.date] ||= []).push(entry); });
  const shows = [...new Map(entries.map(e => [e.key, e])).values()].sort((a, b) => a.key.localeCompare(b.key));
  const labels = Object.fromEntries(shows.map((show, i) => [show.key, SHORT[show.name.toLowerCase()] || `С${i + 1}`]));
  const selected = byDate[selectedDate] || [];
  return <div className="repertoire-calendar">
    <h3>{new Intl.DateTimeFormat('ru', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(first)}</h3>
    <div className="repertoire-calendar-grid" role="group" aria-label="Календарь выбранного варианта">
      {WEEK.map(day => <span className="repertoire-weekday" key={day}>{day}</span>)}
      {Array.from({ length: offset }, (_, i) => <span key={`pad-${i}`} aria-hidden="true" />)}
      {Array.from({ length: last.getUTCDate() }, (_, i) => {
        const day = `${month}-${String(i + 1).padStart(2, '0')}`;
        const events = byDate[day] || [];
        const fixed = events.some(e => e.fixed);
        const pinned = events.some(e => pins.some(p => p.day === day && p.key === e.key));
        return <button type="button" key={day} data-date={day} className={`repertoire-calendar-day${events.length ? ' repertoire-calendar-day--show' : ''}`}
          aria-pressed={selectedDate === day} aria-controls="repertoire-day-detail"
          aria-label={`${dayLabel(day)}: ${events.map(e => e.name).join(', ') || 'Нет показов'}${fixed ? ', уже в расписании' : ''}${pinned ? ', закреплено' : ''}`}
          onClick={() => setSelectedDate(day)}>
          <span>{i + 1}</span>{events.map(e => <small key={e.key}>{labels[e.key]}</small>)}
          {(fixed || pinned) && <span className="repertoire-calendar-mark" aria-hidden="true">{fixed ? '✓' : '●'}</span>}
        </button>;
      })}
    </div>
    <div className="repertoire-calendar-legend">{shows.map(e => <span key={e.key}><strong>{labels[e.key]}</strong> — {e.name}</span>)}<span>✓ Уже в расписании · ● Закреплено</span></div>
    <section id="repertoire-day-detail" className="repertoire-day-detail" aria-live="polite" aria-label={dayLabel(selectedDate)}>
      {selected.length ? selected.map(renderEntry) : <p className="repertoire-note">{dayLabel(selectedDate)} — в выбранном варианте показов нет.</p>}
    </section>
  </div>;
}
