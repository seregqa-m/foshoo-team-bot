import React, { useEffect, useRef, useState } from 'react';
import client from '../api/client';
import './MyAvailabilityView.css';

const ANSWERS = { yes: 'Могу', no: 'Не могу', unknown: 'Пока не знаю' };
const SYMBOLS = { yes: '✓', no: '×', unknown: '?' };
const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const dateLabel = value => new Date(`${value}T12:00:00`).toLocaleDateString('ru-RU', {
  day: 'numeric', month: 'long', weekday: 'short',
});

export default function MyAvailabilityView({ active = true, dataVersion = 0, initialMonth = '', onMonthChange }) {
  const [month, setMonth] = useState(initialMonth);
  const [selectedDate, setSelectedDate] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState('');
  const [refresh, setRefresh] = useState(0);
  const savingRef = useRef(false);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    client.get('/api/attendance/me', month ? { params: { month } } : undefined)
      .then(({ data: result }) => {
        if (!cancelled) { setData(result); onMonthChange?.(result.month); }
      })
      .catch(() => { if (!cancelled) setError('Не удалось загрузить ответы. Нажмите «Обновить».'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [month, refresh, active, dataVersion, onMonthChange]);

  const changeMonth = value => {
    if (!/^(?!0000)\d{4}-(0[1-9]|1[0-2])$/.test(value)) return;
    setMonth(value); setSelectedDate(''); setNotice(''); setData(null);
    onMonthChange?.(value);
  };
  const moveMonth = offset => {
    const [year, number] = (month || data.month).split('-').map(Number);
    const next = new Date(year, number - 1 + offset, 1);
    changeMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`);
  };
  const save = async (day, answer) => {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(day.date); setNotice('');
    try {
      const { data: saved } = await client.put('/api/attendance/me', {
        date: day.date, answer, expected_revision: day.revision,
      });
      setData(current => current && ({ ...current, days: current.days.map(item => item.date === saved.date ? saved : item) }));
      setNotice(`${dateLabel(day.date)}: ${ANSWERS[answer].toLowerCase()}. Сохранено.`);
    } catch (err) {
      setNotice(err.response?.status === 409
        ? 'Ответ уже изменился в другом месте. Обновили данные — проверьте ответ и повторите выбор.'
        : 'Не удалось подтвердить сохранение. Проверьте обновлённый ответ перед повтором.');
    } finally {
      setSaving(''); savingRef.current = false;
      setRefresh(value => value + 1);
    }
  };

  const visibleMonth = month || data?.month || '';
  const [year, monthNumber] = visibleMonth.split('-').map(Number);
  const offset = visibleMonth ? (new Date(year, monthNumber - 1, 1).getDay() + 6) % 7 : 0;
  const daysInMonth = visibleMonth ? new Date(year, monthNumber, 0).getDate() : 0;
  const answersByDate = Object.fromEntries((data?.days || []).map(day => [day.date, day]));
  const selected = answersByDate[selectedDate];

  return <div className="my-availability">
    <div className="my-availability__title">
      <h1>Моя занятость</h1>
      <button className="btn btn-secondary" disabled={!!saving || loading} onClick={() => setRefresh(value => value + 1)}>Обновить</button>
    </div>
    <p className="my-availability__intro">Нажмите на дату, чтобы изменить ответ на этот день.</p>
    <div className="my-availability__toolbar">
      <button className="btn btn-secondary" aria-label="Предыдущий месяц" onClick={() => moveMonth(-1)} disabled={!!saving || (!month && !data)}>←</button>
      <input type="month" aria-label="Месяц занятости" value={month || data?.month || ''}
        disabled={!!saving} onChange={event => changeMonth(event.target.value)} />
      <button className="btn btn-secondary" aria-label="Следующий месяц" onClick={() => moveMonth(1)} disabled={!!saving || (!month && !data)}>→</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {loading && <p role="status" className="my-availability__loading">Загрузка ответов…</p>}
    {!error && data && <>
      <div className="my-availability__calendar" role="group" aria-label="Календарь занятости" aria-busy={loading}>
        {WEEKDAYS.map(day => <span className="my-availability__weekday" key={day}>{day}</span>)}
        {Array.from({ length: offset }, (_, i) => <span key={`empty-${i}`} aria-hidden="true" />)}
        {Array.from({ length: daysInMonth }, (_, i) => {
          const date = `${visibleMonth}-${String(i + 1).padStart(2, '0')}`;
          const day = answersByDate[date];
          const answer = day?.answer || 'unanswered';
          return <button key={date} type="button" data-date={date}
            className={`my-availability__cell my-availability--${answer}${day && !day.editable ? ' my-availability__cell--past' : ''}`}
            aria-label={`${dateLabel(date)}: ${ANSWERS[answer] || 'Нет ответа'}${day && !day.editable ? ', дата прошла' : ''}`}
            aria-pressed={selectedDate === date} disabled={!!saving || loading}
            onClick={() => { setSelectedDate(date); setNotice(''); }}>
            <span>{i + 1}</span><small aria-hidden="true">{SYMBOLS[answer] || '—'}</small>
          </button>;
        })}
      </div>
      <div className="my-availability__legend" aria-label="Обозначения ответов">
        {[...Object.entries(ANSWERS), ['unanswered', 'Нет ответа']].map(([answer, label]) =>
          <span key={answer}><i className={`my-availability--${answer}`} aria-hidden="true">{SYMBOLS[answer] || '—'}</i>{label}</span>)}
      </div>
      {selectedDate ? <section className="my-availability__selection" aria-label={dateLabel(selectedDate)}>
        <div className="my-availability__heading">
          <h2>{dateLabel(selectedDate)}</h2>
          <span>{ANSWERS[selected?.answer] || 'Нет ответа'}</span>
        </div>
        {selected?.editable ? <div className="my-availability__answers" role="group" aria-label={`Ответ на ${dateLabel(selectedDate)}`}>
          {Object.entries(ANSWERS).map(([answer, label]) => <button key={answer}
            className={`my-availability--${answer}`} type="button" aria-pressed={selected.answer === answer}
            disabled={!!saving || loading || selected.answer === answer}
            onClick={() => save(selected, answer)}>{label}</button>)}
        </div> : <p>{selected ? 'Дата прошла — ответ сохранён в истории.' : 'На эту дату вы ещё не отвечали в опросах бота. Здесь можно менять уже отправленные ответы.'}</p>}
        {saving && <small role="status">Сохраняем…</small>}
      </section> : <p className="my-availability__hint">{data.days.length ? 'Выберите день в календаре.' : 'На этот месяц у вас пока нет ответов из опросов.'}</p>}
      {notice && <p role="status" className="my-availability__notice">{notice}</p>}
      <p className="my-availability__hint">Ответ общий для всех спектаклей на эту дату. Отметка в старом Telegram-опросе не меняется.</p>
    </>}
  </div>;
}
