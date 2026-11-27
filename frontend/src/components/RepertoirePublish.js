import React, { useEffect, useRef, useState } from 'react';
import client from '../api/client';

const errorText = e => typeof e.response?.data?.detail === 'string' ? e.response.data.detail : 'Не удалось проверить сохранение. Закройте окно и обновите афишу: результат будет восстановлен с сервера.';
const time = value => value?.slice(11, 16) || 'весь день';

export default function RepertoirePublish({ data, variant, publication, onClose, onApplied }) {
  const [preview, setPreview] = useState(publication || null);
  const [choices, setChoices] = useState({});
  const [locations, setLocations] = useState({});
  const [busy, setBusy] = useState(!publication);
  const [error, setError] = useState('');
  const guard = useRef(false);
  const panel = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    panel.current?.focus();
    return () => previous?.focus?.();
  }, []);
  useEffect(() => {
    if (publication) return;
    let active = true;
    client.post('/api/planning/repertoire/lock/preview', { month: data.month, search_id: data.search_id, variant_id: variant.id,
      expected_fingerprint: data.fingerprint, expected_revision: data.revision }).then(({ data: result }) => {
      if (!active) return;
      setPreview(result);
      setChoices(Object.fromEntries(result.actions.filter(a => a.targets.length === 1).map(a => [a.date, a.targets[0].id])));
    }).catch(e => { if (active) setError(errorText(e)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [data, variant, publication]);
  const continuing = preview && preview.status !== 'preview';
  const valid = preview && (continuing || preview.actions.every(a => a.kind === 'replace' ? !!choices[a.date] : !!locations[a.date]?.trim()));
  const apply = async () => {
    if (guard.current || !valid) return;
    guard.current = true; setBusy(true); setError('');
    try {
      const { data: result } = await client.post('/api/planning/repertoire/lock', { preview_id: preview.id, choices, locations });
      setPreview(result);
      if (result.status === 'complete') onApplied();
    } catch (e) { setError(errorText(e)); }
    finally { guard.current = false; setBusy(false); }
  };
  const stop = async () => {
    if (guard.current) return;
    guard.current = true; setBusy(true); setError('');
    try {
      await client.post('/api/planning/repertoire/lock/stop', { preview_id: preview.id });
      onApplied();
    } catch (e) { setError(errorText(e)); }
    finally { guard.current = false; setBusy(false); }
  };
  const keyboard = e => {
    if (e.key === 'Escape' && !busy) { e.preventDefault(); onClose(); }
    if (e.key !== 'Tab') return;
    const items = [...panel.current.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled)')];
    if (!items.length) { e.preventDefault(); return; }
    const first = items[0], last = items.at(-1);
    if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (document.activeElement === last || document.activeElement === panel.current)) { e.preventDefault(); first.focus(); }
  };
  return <div className="repertoire-modal-overlay"><section className="repertoire-modal" role="dialog" aria-modal="true" aria-labelledby="publish-title" tabIndex={-1} ref={panel} onKeyDown={keyboard}>
    <h3 id="publish-title">Закрепить афишу и обновить календарь</h3>
    <p>Репетиции ниже будут переименованы в спектакли с указанным временем. На свободные даты будут созданы новые события. Афиша месяца сохранится для всех администраторов.</p>
    <p className="repertoire-note">Из повторяющейся серии меняется только выбранная дата. Остальные события сохраняются. Снятие закрепления не откатит изменения календаря. Сообщения в чат не отправляются.</p>
    {busy && <p role="status">{preview ? 'Сохраняем календарь…' : 'Проверяем календарь и готовим изменения…'}</p>}
    {error && <p role="alert" className="planning-warning">{error}</p>}
    {preview && <>
      {preview.existing_count > 0 && <p>Уже назначены и останутся без изменений: {preview.existing_count}.</p>}
      {preview.actions.map(action => {
        const target = action.targets.find(t => t.id === (action.event_id || choices[action.date]));
        return <div className="repertoire-rule" key={action.date}>
          <strong>{action.date} · {action.done ? '✓ Сохранено' : action.kind === 'replace' ? 'Замена репетиции' : 'Новое событие'}</strong>
          {action.kind === 'replace' && <label className="repertoire-field">Какую репетицию заменить<select className="select-input" aria-label={`Репетиция ${action.date}`} disabled={busy || continuing} value={action.event_id || choices[action.date] || ''} onChange={e => setChoices(old => ({ ...old, [action.date]: e.target.value }))}>
            <option value="">Выберите репетицию</option>{action.targets.map(t => <option value={t.id} key={t.id}>{t.title} · {time(t.start_time)}–{time(t.end_time)}</option>)}
          </select></label>}
          {target && <p>Было: {target.title} · {time(target.start_time)}–{time(target.end_time)}{target.recurring && ' · только эта дата серии'}</p>}
          <p>Будет: <strong>{action.title}</strong> · {time(action.start_time)}–{time(action.end_time)}</p>
          {action.kind === 'create' ? <label className="repertoire-field">Место показа<input className="form-input" aria-label={`Место ${action.date}`} maxLength={500} disabled={busy || continuing} value={action.body?.location || locations[action.date] || ''} onChange={e => setLocations(old => ({ ...old, [action.date]: e.target.value }))} /></label> : <p>Место: {target?.location || 'не указано в репетиции'}. Описание события сохраняется.</p>}
        </div>;
      })}
      {preview.error && <p className="planning-warning" role="alert">{preview.error} Сохранено: {preview.done} из {preview.actions.length}.</p>}
    </>}
    {continuing && <p className="repertoire-note">Можно остановить оставшиеся изменения. Уже созданные и переименованные события останутся в календаре, афиша не будет закреплена.</p>}
    <div className="repertoire-actions">
      {continuing && <button type="button" className="btn btn-secondary" disabled={busy} onClick={stop}>Остановить оставшиеся изменения</button>}
      <button type="button" className="btn btn-primary" disabled={busy || !valid} onClick={apply}>{continuing ? 'Продолжить сохранение' : 'Подтвердить и обновить календарь'}</button>
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>Закрыть</button>
    </div>
  </section></div>;
}
