import React, { useEffect, useState } from 'react';
import client from '../api/client';

export default function RepertoireDayOptions({ month, day, data, entries, disabled, onReplace, onRefresh }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setLoading(true); setResult(null); setError('');
    client.get('/api/planning/repertoire/day', { params: { month, day } }).then(({ data: value }) => {
      if (active) { if (!Array.isArray(value.shows) || value.day !== day) throw new Error('Invalid day'); setResult(value); }
    }).catch(() => { if (active) setError('Не удалось загрузить ответы на эту дату. Обновите план.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [month, day, data.fingerprint, data.revision, data.checked_at]);
  const current = entries.find(e => e.date === day);
  const stale = result && (result.fingerprint !== data.fingerprint || result.revision !== data.revision);
  return <section className="repertoire-day-options" aria-label="Спектакли и ответы на выбранную дату">
    <h4>Спектакли на эту дату</h4>
    <p className="repertoire-note">Общие ответы актёров на день. Замена меняет только этот день черновика; остальные даты сохраняются.</p>
    {loading && <p role="status">Загружаем ответы…</p>}
    {(error || stale) && <p role="alert">{error || 'Ответы или календарь обновились.'} <button type="button" className="btn btn-secondary" onClick={onRefresh}>Обновить план</button></p>}
    {current?.fixed && <p className="repertoire-note">Этот показ уже назначен. Его изменение выполняется в основном календаре.</p>}
    {result?.shows.map(show => <div className="repertoire-day-option" key={show.key}>
      <div className="repertoire-row"><strong>{show.name}</strong><span>{show.start_time?.slice(11, 16)}</span></div>
      <p className="repertoire-note">Роли: {show.covered}/{show.total} · Смогут: {show.votes.yes} · Не смогут: {show.votes.no} · Не определились / нет ответа: {show.votes.other}</p>
      {show.reason && <p className="planning-warning">{show.reason}</p>}
      <details><summary>Ответы по ролям — {show.name}</summary>{show.roles.map(role => <div key={role.name} className="repertoire-vote-role"><strong>{role.name}</strong>
        <ul>{role.actors.map(actor => <li key={actor.name} className={`planning-actor--${actor.status}`}>{actor.name} — {actor.reason}</li>)}</ul>
      </div>)}</details>
      {current?.key === show.key ? <p className="repertoire-note">Выбран в этом варианте</p> : <button type="button" className="btn btn-secondary" disabled={disabled || loading || !!stale || !!show.reason || !!current?.fixed}
        onClick={() => onReplace(day, show.key)}>{current ? `Заменить на «${show.name}»` : `Поставить «${show.name}»`}</button>}
    </div>)}
  </section>;
}
