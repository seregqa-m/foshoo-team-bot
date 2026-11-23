import React, { useEffect, useRef, useState } from 'react';
import client from '../api/client';
import './MyAvailabilityView.css';

const ANSWERS = { yes: 'Могу', no: 'Не могу', unknown: 'Пока не знаю' };
const SYMBOLS = { yes: '✓', no: '×', unknown: '?' };
const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const dateLabel = value => new Date(`${value}T12:00:00`).toLocaleDateString('ru-RU', {
  day: 'numeric', month: 'long', weekday: 'short',
});

export default function MyAvailabilityView({ active = true, dataVersion = 0, initialMonth = '', onMonthChange, isSuperAdmin = false }) {
  const [month, setMonth] = useState(initialMonth);
  const [selectedDate, setSelectedDate] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState('');
  const [refresh, setRefresh] = useState(0);
  const savingRef = useRef(false);
  const [targetId, setTargetId] = useState('');
  const [participants, setParticipants] = useState([]);
  const [participantsError, setParticipantsError] = useState('');
  const [participantsLoading, setParticipantsLoading] = useState(false);
  const [rosterRefresh, setRosterRefresh] = useState(0);
  const delegated = isSuperAdmin && !!targetId;
  const endpoint = delegated ? `/api/attendance/participants/${targetId}` : '/api/attendance/me';
  const participant = participants.find(person => String(person.telegram_user_id) === targetId);

  useEffect(() => {
    if (!active || !isSuperAdmin) return;
    let cancelled = false;
    setParticipantsLoading(true); setParticipantsError('');
    client.get('/api/attendance/participants')
      .then(({ data: result }) => {
        if (cancelled) return;
        setParticipants(result.participants);
        if (result.incomplete) setParticipantsError('Не всех участников удалось проверить. Нажмите «Обновить».');
      })
      .catch(() => { if (!cancelled) setParticipantsError('Не удалось загрузить участников. Нажмите «Обновить».'); })
      .finally(() => { if (!cancelled) setParticipantsLoading(false); });
    return () => { cancelled = true; };
  }, [active, isSuperAdmin, dataVersion, rosterRefresh]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true);
    setData(current => current?.endpoint === endpoint ? current : null);
    setError('');
    client.get(endpoint, month ? { params: { month } } : undefined)
      .then(({ data: result }) => {
        if (!cancelled) { setData({ ...result, endpoint }); onMonthChange?.(result.month); }
      })
      .catch(err => { if (!cancelled) setError(err.response?.status === 403
        ? 'Нет доступа к ответам этого участника. Обновите список участников.'
        : 'Не удалось загрузить ответы. Нажмите «Обновить».'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [month, refresh, active, dataVersion, onMonthChange, endpoint]);

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
      const { data: saved } = await client.put(endpoint, {
        date: day.date, answer, expected_revision: day.revision,
      });
      setData(current => current && ({ ...current, days: [...current.days.filter(item => item.date !== saved.date), saved] }));
      setNotice(`${delegated ? `${participant?.name || 'Участник'} — ` : ''}${dateLabel(day.date)}: ${ANSWERS[answer].toLowerCase()}. Сохранено.`);
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
  const selected = answersByDate[selectedDate] || (delegated && data?.can_create && selectedDate ? {
    date: selectedDate, answer: null, revision: 0, editable: selectedDate >= data.today,
  } : null);

  return <div className="my-availability">
    <div className="my-availability__title">
      <h1>Мои даты</h1>
      <button className="btn btn-secondary" disabled={!!saving || loading || participantsLoading} onClick={() => {
        setRefresh(value => value + 1); setRosterRefresh(value => value + 1);
      }}>Обновить</button>
    </div>
    {isSuperAdmin && <div className="my-availability__participant">
      <label htmlFor="attendance-participant">Чьи даты</label>
      <select id="attendance-participant" value={targetId} disabled={!!saving || participantsLoading}
        onChange={event => {
          setMonth(visibleMonth); setTargetId(event.target.value); setSelectedDate(''); setData(null); setNotice('');
        }}>
        <option value="">Мои даты</option>
        {targetId && !participant && <option value={targetId}>Участник {targetId} — недоступен</option>}
        {participants.map(person => <option key={person.telegram_user_id} value={person.telegram_user_id}>
          {person.name} ({person.username ? `@${person.username}` : `ID ${person.telegram_user_id}`})
        </option>)}
      </select>
      {participantsLoading && <p role="status">Загрузка участников…</p>}
      {participantsError && <p role="alert">{participantsError}</p>}
      <p className="my-availability__hint">Нет человека в списке? Попросите его открыть мини-приложение через бота, затем обновите список.</p>
    </div>}
    {delegated && <p className="my-availability__acting" role="status">Вы отвечаете за: <strong>{participant?.name || `Участник ${targetId}`}</strong></p>}
    <p className="my-availability__intro">Нажмите на дату, чтобы изменить ответ на этот день.</p>
    <div className="my-availability__toolbar">
      <button className="btn btn-secondary" aria-label="Предыдущий месяц" onClick={() => moveMonth(-1)} disabled={!!saving || (!month && !data)}>←</button>
      <input type="month" aria-label="Месяц" value={month || data?.month || ''}
        disabled={!!saving} onChange={event => changeMonth(event.target.value)} />
      <button className="btn btn-secondary" aria-label="Следующий месяц" onClick={() => moveMonth(1)} disabled={!!saving || (!month && !data)}>→</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {loading && <p role="status" className="my-availability__loading">Загрузка ответов…</p>}
    {!error && data && data.endpoint === endpoint && <>
      <div className="my-availability__calendar" role="group" aria-label={delegated ? `Даты: ${participant?.name || targetId}` : 'Мои даты'} aria-busy={loading}>
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
        </div> : <p>{selected ? 'Дата прошла — изменение недоступно.' : 'На эту дату вы ещё не отвечали в опросах бота. Здесь можно менять уже отправленные ответы.'}</p>}
        {saving && <small role="status">Сохраняем…</small>}
      </section> : <p className="my-availability__hint">{delegated ? 'Выберите день — можно внести ответ и без опроса бота.' : data.days.length ? 'Выберите день в календаре.' : 'На этот месяц у вас пока нет ответов из опросов.'}</p>}
      {notice && <p role="status" className="my-availability__notice">{notice}</p>}
      <p className="my-availability__hint">Ответ общий для всех спектаклей на эту дату. Отметка в старом Telegram-опросе не меняется.</p>
    </>}
  </div>;
}
