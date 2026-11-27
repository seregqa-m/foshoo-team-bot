import React, { useEffect, useState } from 'react';
import client from '../api/client';

const voteText = actor => ({ yes: 'Сможет', no: 'Не сможет', unknown: 'Не определился', unanswered: 'Нет ответа' }[actor.vote] || actor.reason);
function VoteCounts({ votes }) {
  return <p className="repertoire-vote-counts"><span>Смогут: {votes.yes}</span> · <span>Не смогут: {votes.no}</span> · {votes.unknown === undefined
    ? <span>Не определились / нет ответа: {votes.other}</span>
    : <><span>Не определились: {votes.unknown}</span> · <span>Нет ответа: {votes.unanswered}</span></>}</p>;
}

export default function RepertoireDayOptions({ month, day, data, entries, disabled, onReplace, onRefresh }) {
  const [lastResult, setResult] = useState(null);
  // Keep this day's cards mounted during polling; clearing them shifts the table below.
  const result = lastResult?.day === day ? lastResult : null;
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    client.get('/api/planning/repertoire/day', { params: { month, day } }).then(({ data: value }) => {
      if (active) { if (!Array.isArray(value.shows) || value.day !== day) throw new Error('Invalid day'); setResult(value); }
    }).catch(() => { if (active) setError('Не удалось загрузить ответы на эту дату. Обновите план.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [month, day, data.fingerprint, data.revision, data.checked_at]);
  const current = entries.find(e => e.date === day);
  const stale = result && (result.fingerprint !== data.fingerprint || result.revision !== data.revision);
  const selected = result?.shows.find(s => s.key === current?.key);
  const actors = selected ? [...new Map(selected.roles.flatMap(r => r.actors).map(a => [a.name.trim().toLocaleLowerCase('ru'), a])).values()] : [];
  return <section className="repertoire-day-options" aria-label="Спектакли и ответы на выбранную дату" aria-busy={loading}>
    {loading && !result && <p role="status">Загружаем ответы…</p>}
    {(error || (stale && !loading)) && <p role="alert">{error || 'Ответы или календарь обновились.'} {result && 'Показаны последние полученные ответы.'} <button type="button" className="btn btn-secondary" onClick={onRefresh}>Обновить план</button></p>}
    {current && <div className="repertoire-vote-summary" aria-label={`Ответы на «${selected?.name || current.name || ''}»`}>
      <strong>Ответы на эту дату · {selected?.name || current.name}</strong>
      {selected ? <><VoteCounts votes={selected.votes} />
        <details><summary>Кто как ответил</summary><ul>{actors.map(actor => <li key={actor.name}>{actor.name} — {voteText(actor)}</li>)}</ul></details>
      </> : !loading && !error && !stale && <p>Ответы по этому спектаклю недоступны.</p>}
      <p className="repertoire-note">Исполнители на роли здесь не назначаются.</p>
    </div>}
    {current?.fixed && <p className="repertoire-note">Этот показ уже внесён в календарь. Его изменение выполняется в основном календаре.</p>}
    <h4>{current ? 'Другие спектакли на эту дату' : 'Спектакли на эту дату'}</h4>
    <p className="repertoire-note">Общие ответы актёров на день. Замена меняет только этот день черновика; остальные даты сохраняются.</p>
    {result?.shows.filter(show => show.key !== current?.key).map(show => <div className="repertoire-day-option" key={show.key}>
      <div className="repertoire-row"><strong>{show.name}</strong><span>{show.start_time?.slice(11, 16)}</span></div>
      <VoteCounts votes={show.votes} />
      <p className="repertoire-note">По ответам закрываются роли: {show.covered}/{show.total}</p>
      {show.reason && <p className="planning-warning">{show.reason}</p>}
      <details><summary>Ответы по ролям — {show.name}</summary>{show.roles.map(role => <div key={role.name} className="repertoire-vote-role"><strong>{role.name}</strong>
        <ul>{role.actors.map(actor => <li key={actor.name} className={`planning-actor--${actor.vote || actor.status}`}>{actor.name} — {voteText(actor)}</li>)}</ul>
      </div>)}</details>
      <button type="button" className="btn btn-secondary" disabled={disabled || loading || !!error || !!stale || !!show.reason || !!current?.fixed}
        onClick={() => onReplace(day, show.key)}>{current ? `Заменить на «${show.name}»` : `Поставить «${show.name}»`}</button>
    </div>)}
  </section>;
}
