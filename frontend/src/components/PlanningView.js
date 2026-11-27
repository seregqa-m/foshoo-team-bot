import React, { useEffect, useState } from 'react';
import client from '../api/client';
import './PlanningView.css';
import AvailabilitySection from './AvailabilitySection';
import RepertoirePlan from './RepertoirePlan';

import CastDialog, { AttendanceSummary, STATUS } from './CastDialog';

export default function PlanningView({ onClose, closeLabel = '← К расписанию', dataVersion = 0, initialMonth = '', userId, isAdmin = false, isSuperAdmin = false }) {
  const [showNames, setShowNames] = useState([]);
  useEffect(() => {
    if (!isAdmin) return;
    let active = true;
    client.get('/api/sheets/shows')
      .then(({ data }) => { if (active) setShowNames(data.shows || []); })
      .catch(() => {});
    return () => { active = false; };
  }, [isAdmin]);
  const [month, setMonth] = useState(initialMonth);
  const [resolvedMonth, setResolvedMonth] = useState(initialMonth);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [show, setShow] = useState('');
  const [readyOnly, setReadyOnly] = useState(false);
  const [selected, setSelected] = useState(null);
  const [success, setSuccess] = useState('');
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const updateToday = () => setNow(Date.now());
    const timer = setInterval(updateToday, 60_000);
    window.addEventListener('focus', updateToday);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', updateToday);
    };
  }, []);
  const todayParts = new Intl.DateTimeFormat('en', {
    timeZone: data?.timezone || 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now);
  const today = ['year', 'month', 'day'].map(type => todayParts.find(part => part.type === type).value).join('-');
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setData(null); setSelected(null);
    client.get('/api/planning', month ? { params: { month } } : undefined)
      .then(({ data: result }) => { if (active) { setData(result); setResolvedMonth(result.month); } })
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
      <button className="btn btn-secondary" onClick={onClose}>{closeLabel}</button>
      {isAdmin && <details className="planning-polls">
        <summary>Отправленные опросы и пинг неответивших</summary>
        <AvailabilitySection showNames={showNames} />
      </details>}
      <h1>Планирование составов</h1>
      <p className="planning-note">Сравните даты и спектакли. Нажмите на ячейку, чтобы посмотреть роли и доступность исполнителей.{isAdmin && ' Администратор может выбрать состав и назначить спектакль.'}</p>
      <div className="planning-toolbar">
        <button className="btn btn-secondary" aria-label="Предыдущий месяц планирования" disabled={!(month || data?.month)} onClick={() => move(-1)}>‹</button>
        <input aria-label="Месяц планирования" className="form-input" type="month" value={month || data?.month || ''} onChange={e => changeMonth(e.target.value)} />
        <button className="btn btn-secondary" aria-label="Следующий месяц планирования" disabled={!(month || data?.month)} onClick={() => move(1)}>›</button>
        <button className="btn btn-secondary" onClick={() => setRevision(n => n + 1)} disabled={loading}>Обновить</button>
      </div>
      {isAdmin && (month || resolvedMonth) && <RepertoirePlan isSuperAdmin={isSuperAdmin} key={`${month || resolvedMonth}:${userId || ''}`} userId={userId} onCastSaved={() => setRevision(n => n + 1)} month={month || resolvedMonth} dataVersion={`${dataVersion}:${revision}`} />}
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
        <p className="planning-note">Дробь — закрытые роли / все роли. Учитываются все зарегистрированные участники чата спектакля, даже если роли ещё не заполнены. Пока человек не голосовал и бот не получил событие его вступления, его может не быть в списке.</p>
        {data.warnings.map(warning => <div className="planning-warning" key={warning}>{warning}</div>)}
        {!data.shows.length ? <div className="empty-state">{isAdmin ? 'Добавьте роли и исполнителей в «Составы спектаклей».' : 'Роли и исполнители пока не заполнены.'}</div>
          : !data.slots.length ? <div className="empty-state">В этом месяце нет дат в графике.{isAdmin && ' Запустите опрос на нужный месяц.'}</div>
          : !slots.length ? <div className="empty-state">Полный состав пока не собирается. Выключите фильтр, чтобы увидеть, каких ответов или исполнителей не хватает.</div>
          : <div className="planning-table-scroll" tabIndex="0" aria-label="Сводка составов по датам">
            <table className="planning-table"><thead><tr><th scope="col">Дата</th>{visibleShows.map(name => <th scope="col" key={name}>{name}</th>)}</tr></thead>
              <tbody>{slots.map(slot => <tr key={slot.column} className={slot.date === today ? 'planning-row--today' : undefined}>
                <th scope="row" aria-current={slot.date === today ? 'date' : undefined}>
                  {slot.date === today && <span className="planning-today">Сегодня</span>}
                  {slot.label.replace(/\n/g, ' ')}{slot.assigned_show && <small>{slot.assigned_show}</small>}
                </th>
                {visibleShows.map(name => {
                  const cell = slot.shows.find(item => item.show === name);
                  const pending = slot.operation?.show_name === name && slot.operation.status !== 'complete';
                  return <td key={name}><button className={`planning-cell planning-cell--${cell.status}`} onClick={() => setSelected({ column: slot.column, show: name })}
                    aria-label={`${name}, ${slot.label}: ${STATUS[cell.status]}`}>
                    <strong>{cell.covered}/{cell.total}</strong><span>{pending ? 'Не завершено' : STATUS[cell.status]}</span>
                    <AttendanceSummary data={cell.attendance} />
                  </button></td>;
                })}
              </tr>)}</tbody>
            </table>
          </div>}
        <p className="planning-note">Ответы из всех чатов и обоих типов опросов общие на дату. Последнее изменение ответа учитывается для всех спектаклей. Один человек занимает одну роль. Назначение на другую дату не меняет остальные ответы.</p>
      </>}
      {selectedSlot && selectedCell && <CastDialog key={`${selectedSlot.column}:${selectedCell.show}`} slot={selectedSlot} cell={selectedCell}
        month={data.month} fingerprint={data.fingerprint} timezone={data.timezone} onClose={() => setSelected(null)} onSaved={saved} isAdmin={isAdmin} initialCast={selected?.cast} repertoireContext={selected?.repertoire} />}
    </div>
  );
}
