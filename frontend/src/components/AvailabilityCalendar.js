import React from 'react';
import './AvailabilityCalendar.css';

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

export default function AvailabilityCalendar({ month, selectedDates, suggestedDates, onToggle, disabled }) {
  const [year, monthNumber] = month.split('-').map(Number);
  const first = new Date(year, monthNumber - 1, 1);
  const offset = (first.getDay() + 6) % 7;
  const days = new Date(year, monthNumber, 0).getDate();
  const label = first.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' });

  return (
    <div className="availability-calendar" role="group" aria-label={`Даты опроса: ${label}`}>
      <div className="availability-calendar__title">{label}</div>
      <p className="availability-calendar__hint">Даты из расписания уже выбраны. Нажмите на день, чтобы добавить или убрать его.</p>
      <div className="availability-calendar__grid">
        {WEEKDAYS.map(day => <span className="availability-calendar__weekday" key={day}>{day}</span>)}
        {Array.from({ length: offset }, (_, i) => <span key={`empty-${i}`} aria-hidden="true" />)}
        {Array.from({ length: days }, (_, i) => {
          const day = i + 1;
          const date = `${month}-${String(day).padStart(2, '0')}`;
          const selected = selectedDates.includes(date);
          const suggested = suggestedDates.includes(date);
          return (
            <button
              type="button" key={date} disabled={disabled}
              className={`availability-calendar__day${selected ? ' availability-calendar__day--selected' : ''}`}
              aria-pressed={selected} aria-label={`${day} ${label}${suggested ? ', есть в расписании' : ''}`}
              title={suggested ? 'Есть в расписании' : 'Добавить дату в опрос'}
              onClick={() => onToggle(date)}
            >
              {day}
              {suggested && <span className="availability-calendar__dot" aria-hidden="true" />}
            </button>
          );
        })}
      </div>
      <div className="availability-calendar__legend"><span aria-hidden="true">●</span> Есть в расписании</div>
      <div className="availability-calendar__count" role="status">Выбрано дат: {selectedDates.length}</div>
    </div>
  );
}
