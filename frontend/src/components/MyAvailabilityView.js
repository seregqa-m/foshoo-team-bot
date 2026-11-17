import React, { useEffect, useRef, useState } from 'react';
import client from '../api/client';
import './MyAvailabilityView.css';

const ANSWERS = { yes: 'Могу', no: 'Не могу', unknown: 'Пока не знаю' };
const dateLabel = value => new Date(`${value}T12:00:00`).toLocaleDateString('ru-RU', {
  day: 'numeric', month: 'long', weekday: 'short',
});

export default function MyAvailabilityView({ onClose, active = true, dataVersion = 0 }) {
  const [month, setMonth] = useState('');
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
      .then(({ data: result }) => { if (!cancelled) setData(result); })
      .catch(() => { if (!cancelled) setError('Не удалось загрузить ответы. Нажмите «Обновить».'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [month, refresh, active, dataVersion]);

  const changeMonth = value => {
    if (!/^\d{4}-\d{2}$/.test(value)) return;
    setMonth(value); setNotice(''); setData(null);
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
      await client.put('/api/attendance/me', {
        date: day.date, answer, expected_revision: day.revision,
      });
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

  return <div className="my-availability">
    <button className="btn btn-secondary" onClick={onClose} disabled={!!saving}>← К расписанию</button>
    <h1>Моя занятость</h1>
    <p>Здесь ваши ответы из опросов. Выберите ответ под нужной датой — он сохранится сразу.
      Остальные дни не изменятся. Ответ действует на весь день для всех спектаклей.</p>
    <div className="my-availability__toolbar">
      <button className="btn btn-secondary" aria-label="Предыдущий месяц" onClick={() => moveMonth(-1)} disabled={!!saving || (!month && !data)}>←</button>
      <input type="month" aria-label="Месяц занятости" value={month || data?.month || ''}
        disabled={!!saving} onChange={event => changeMonth(event.target.value)} />
      <button className="btn btn-secondary" aria-label="Следующий месяц" onClick={() => moveMonth(1)} disabled={!!saving || (!month && !data)}>→</button>
      <button className="btn btn-secondary" disabled={!!saving || loading} onClick={() => setRefresh(value => value + 1)}>Обновить</button>
    </div>
    {notice && <p role="status" className="my-availability__notice">{notice}</p>}
    {error && <p role="alert">{error}</p>}
    {loading ? <p role="status">Загрузка ответов…</p> : !error && data && <>
      {!data.days.length && <p>На этот месяц у вас пока нет ответов. Здесь появятся даты, на которые вы ответили в опросах бота.</p>}
      {data.days.map(day => <section key={day.date} className="my-availability__day" aria-label={dateLabel(day.date)}>
        <div className="my-availability__heading">
          <h2>{dateLabel(day.date)}</h2>
          <span>{ANSWERS[day.answer] || 'Нет ответа'}</span>
        </div>
        {day.editable ? <div className="my-availability__answers" role="group" aria-label={`Ответ на ${dateLabel(day.date)}`}>
          {Object.entries(ANSWERS).map(([answer, label]) => <button key={answer}
            type="button" aria-pressed={day.answer === answer}
            disabled={!!saving || day.answer === answer}
            onClick={() => save(day, answer)}>{label}</button>)}
        </div> : <small>Дата прошла — ответ сохранён в истории.</small>}
        {saving === day.date && <small role="status">Сохраняем…</small>}
      </section>)}
      <p className="my-availability__hint">Изменения учитываются в планировании. Отметки в старом Telegram-опросе при этом не меняются.</p>
    </>}
  </div>;
}
