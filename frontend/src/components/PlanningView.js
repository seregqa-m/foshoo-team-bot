import React, { useEffect, useState } from 'react';
import client from '../api/client';
import './PlanningView.css';

const STATUS = { ready: 'Состав собирается', waiting: 'Ждём ответы', blocked: 'Не хватает исполнителей', occupied: 'Дата занята', ambiguous: 'Дубли даты в графике' };
const canPlay = actor => ['yes', 'assigned'].includes(actor.status);
const errorText = error => typeof error.response?.data?.detail === 'string' ? error.response.data.detail : 'Не удалось сохранить. Обновите сводку и проверьте результат.';

function CastDialog({ slot, cell, month, fingerprint, timezone, onClose, onSaved }) {
  const pending = slot.operation?.show_name === cell.show && slot.operation.status !== 'complete' ? slot.operation : null;
  const [cast, setCast] = useState(pending?.cast || cell.suggested_cast);
  const [start, setStart] = useState(pending?.start_time.slice(0, 16) || `${slot.date}T19:00`);
  const [end, setEnd] = useState(pending?.end_time.slice(0, 16) || `${slot.date}T21:00`);
  const [location, setLocation] = useState(pending?.location || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [mustRefresh, setMustRefresh] = useState(false);
  const duplicate = new Set(Object.values(cast).filter(Boolean).map(a => a.trim().toLowerCase())).size !== Object.values(cast).filter(Boolean).length;
  const complete = cell.roles.length > 0 && cell.roles.every(role => role.actors.some(a => a.name === cast[role.name] && canPlay(a)));
  const assignable = !slot.operation && !cell.incomplete && !slot.assigned_show && cell.status === 'ready';
  const save = async event => {
    event.preventDefault();
    if (saving || mustRefresh || (!pending && (!complete || duplicate || !assignable))) return;
    setSaving(true); setError('');
    try {
      await client.post('/api/planning/assign', {
        month, column: slot.column, show_name: cell.show, cast,
        expected_fingerprint: fingerprint,
        start_time: pending?.start_time || start, end_time: pending?.end_time || end, location,
      });
      onSaved();
    } catch (e) { setError(errorText(e)); setMustRefresh(true); }
    finally { setSaving(false); }
  };
  return (
    <div className="modal-overlay">
      <div className="modal planning-dialog" role="dialog" aria-modal="true" aria-labelledby="cast-title">
        <div className="planning-dialog__heading">
          <h2 id="cast-title">{cell.show}</h2>
          <button className="btn btn-secondary" onClick={onClose} disabled={saving} aria-label="Закрыть состав">×</button>
        </div>
        <p>{slot.label.replace(/\n/g, ' ')} · {STATUS[cell.status]}</p>
        {slot.assigned_show && <p>В графике: <strong>{slot.assigned_show}</strong></p>}
        {cell.incomplete && <div className="alert alert-error">В «Составы спектаклей» есть незаполненные роли или исполнители. Дополните список.</div>}
        {pending && <div className="alert alert-error">Предыдущее сохранение не завершено. Продолжите с теми же временем и составом.</div>}
        <form onSubmit={save}>
          <p className="planning-note">Каждая роль — отдельный исполнитель. Можно заменить предложенного актёра на другого свободного.</p>
          {cell.roles.map(role => (
            <div className="planning-role" key={role.name}>
              <label><strong>{role.name}</strong>
                <select className="select-input" aria-label={`Исполнитель: ${role.name}`} value={cast[role.name] || ''}
                  disabled={saving || !!pending || !assignable} onChange={e => setCast(old => ({ ...old, [role.name]: e.target.value }))}>
                  <option value="">Нет исполнителя</option>
                  {role.actors.map(actor => <option key={actor.name} value={actor.name} disabled={!canPlay(actor)}>{actor.name} — {actor.reason}</option>)}
                </select>
              </label>
              <ul>{role.actors.map(actor => <li key={actor.name} className={`planning-actor--${actor.status}`}>{actor.name}: {actor.reason}</li>)}</ul>
            </div>
          ))}
          {duplicate && <div className="alert alert-error" role="alert">Один актёр выбран на несколько ролей. Выберите разных исполнителей.</div>}
          {(assignable || pending) && <>
            <p className="planning-note">Время: {timezone}. Сохранение создаст событие в расписании и запишет спектакль и роли в график.</p>
            <label className="planning-field">Начало<input className="form-input" type="datetime-local" value={start} required disabled={saving || !!pending} onChange={e => setStart(e.target.value)} /></label>
            <label className="planning-field">Окончание<input className="form-input" type="datetime-local" value={end} min={start} required disabled={saving || !!pending} onChange={e => setEnd(e.target.value)} /></label>
            <label className="planning-field">Место<input className="form-input" value={location} required disabled={saving || !!pending} onChange={e => setLocation(e.target.value)} placeholder="Зал или адрес" /></label>
          </>}
          {error && <div className="alert alert-error" role="alert">{error}</div>}
          {(assignable || pending) && <button className="btn btn-primary planning-save" type="submit"
            disabled={saving || mustRefresh || (!pending && (!complete || duplicate))}>
            {saving ? 'Сохраняем...' : pending ? 'Продолжить сохранение' : 'Назначить спектакль'}
          </button>}
          {mustRefresh && <button className="btn btn-secondary planning-save" type="button" onClick={() => onSaved(false)}>Обновить сводку</button>}
        </form>
      </div>
    </div>
  );
}

export default function PlanningView({ onClose, dataVersion = 0 }) {
  const [month, setMonth] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [show, setShow] = useState('');
  const [readyOnly, setReadyOnly] = useState(false);
  const [selected, setSelected] = useState(null);
  const [success, setSuccess] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setData(null); setSelected(null);
    client.get('/api/planning', month ? { params: { month } } : undefined)
      .then(({ data: result }) => { if (active) setData(result); })
      .catch(() => { if (active) setError('Не удалось загрузить график и составы. Нажмите «Обновить».'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [month, revision, dataVersion]);
  const changeMonth = value => { if (value) { setMonth(value); setSuccess(''); } };
  const move = offset => {
    const [y, m] = (month || data.month).split('-').map(Number);
    const next = new Date(y, m - 1 + offset, 1);
    changeMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`);
  };
  const visibleShows = data?.shows.filter(name => !show || name === show) || [];
  const slots = data?.slots.filter(slot => !readyOnly || slot.shows.some(cell => visibleShows.includes(cell.show) && cell.status === 'ready')) || [];
  const selectedSlot = data?.slots.find(slot => slot.column === selected?.column);
  const selectedCell = selectedSlot?.shows.find(cell => cell.show === selected?.show);
  const saved = (ok = true) => {
    setSelected(null); setSuccess(ok ? 'Спектакль создан в расписании, состав записан в график.' : ''); setRevision(n => n + 1);
  };
  return (
    <div className="planning-view">
      <button className="btn btn-secondary" onClick={onClose}>← К расписанию</button>
      <h1>Планирование составов</h1>
      <p className="planning-note">Сравните даты и спектакли. Нажмите на ячейку, чтобы посмотреть роли и выбрать исполнителей.</p>
      <div className="planning-toolbar">
        <button className="btn btn-secondary" aria-label="Предыдущий месяц планирования" disabled={!(month || data?.month)} onClick={() => move(-1)}>‹</button>
        <input aria-label="Месяц планирования" className="form-input" type="month" value={month || data?.month || ''} onChange={e => changeMonth(e.target.value)} />
        <button className="btn btn-secondary" aria-label="Следующий месяц планирования" disabled={!(month || data?.month)} onClick={() => move(1)}>›</button>
        <button className="btn btn-secondary" onClick={() => setRevision(n => n + 1)} disabled={loading}>Обновить</button>
      </div>
      {success && <div className="alert alert-success" role="status">{success}</div>}
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {loading && <div className="empty-state" role="status">Загружаем график и составы...</div>}
      {data && <>
        <div className="planning-filters">
          <select className="select-input" aria-label="Спектакль" value={show} onChange={e => setShow(e.target.value)}>
            <option value="">Все спектакли</option>{data.shows.map(name => <option key={name}>{name}</option>)}
          </select>
          <label><input type="checkbox" checked={readyOnly} onChange={e => setReadyOnly(e.target.checked)} /> Только даты с полным составом</label>
        </div>
        <p className="planning-note">Числа — закрытые роли / все роли. «Ждём ответы» не означает, что состав уже собран.</p>
        {data.warnings.map(warning => <div className="planning-warning" key={warning}>{warning}</div>)}
        {!data.shows.length ? <div className="empty-state">Добавьте роли и исполнителей в «Составы спектаклей».</div>
          : !data.slots.length ? <div className="empty-state">В этом месяце нет дат в графике. Запустите опрос занятости на нужный месяц.</div>
          : !slots.length ? <div className="empty-state">Полный состав пока не собирается. Выключите фильтр, чтобы увидеть, каких ответов или исполнителей не хватает.</div>
          : <div className="planning-table-scroll" tabIndex="0" aria-label="Сводка составов по датам">
            <table className="planning-table"><thead><tr><th scope="col">Дата</th>{visibleShows.map(name => <th scope="col" key={name}>{name}</th>)}</tr></thead>
              <tbody>{slots.map(slot => <tr key={slot.column}>
                <th scope="row">{slot.label.replace(/\n/g, ' ')}{slot.assigned_show && <small>{slot.assigned_show}</small>}</th>
                {visibleShows.map(name => {
                  const cell = slot.shows.find(item => item.show === name);
                  const pending = slot.operation?.show_name === name && slot.operation.status !== 'complete';
                  return <td key={name}><button className={`planning-cell planning-cell--${cell.status}`} onClick={() => setSelected({ column: slot.column, show: name })}
                    aria-label={`${name}, ${slot.label}: ${STATUS[cell.status]}`}>
                    <strong>{cell.covered}/{cell.total}</strong><span>{pending ? 'Не завершено' : STATUS[cell.status]}</span>
                  </button></td>;
                })}
              </tr>)}</tbody>
            </table>
          </div>}
        <p className="planning-note">Ответы читаются из «График [составы]», куда их записывает бот. Один человек занимает одну роль. Назначение на другую дату не меняет остальные ответы.</p>
      </>}
      {selectedSlot && selectedCell && <CastDialog key={`${selectedSlot.column}:${selectedCell.show}`} slot={selectedSlot} cell={selectedCell}
        month={data.month} fingerprint={data.fingerprint} timezone={data.timezone} onClose={() => setSelected(null)} onSaved={saved} />}
    </div>
  );
}
