import React, { useCallback, useEffect, useRef, useState } from 'react';
import client from '../api/client';
import './RepertoirePlan.css';
import RepertoireCalendar from './RepertoireCalendar';
import RepertoireShare from './RepertoireShare';
import RepertoireDayOptions from './RepertoireDayOptions';
import RepertoireAlternatives from './RepertoireAlternatives';
import RepertoirePublish from './RepertoirePublish';
import RepertoireShowTime from './RepertoireShowTime';

const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const prettyDate = day => new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short', weekday: 'short', timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`));
const message = e => typeof e.response?.data?.detail === 'string' ? e.response.data.detail : 'Не удалось обновить план. Проверьте соединение и повторите.';
const copy = value => JSON.parse(JSON.stringify(value));
const draftEntry = entry => ({ day: entry.date, key: entry.key, ...(entry.start_time ? { start_time: entry.start_time.slice(11, 16) } : {}) });
const readDraft = (key, month) => {
  if (!key) return null;
  try {
    const entries = JSON.parse(localStorage.getItem(key));
    return Array.isArray(entries) && entries.length <= 31 && entries.every(e => e && typeof e.day === 'string'
      && e.day.startsWith(`${month}-`) && /^\d{4}-\d{2}-\d{2}$/.test(e.day) && typeof e.key === 'string' && e.key.length <= 250
      && (e.start_time == null || (typeof e.start_time === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(e.start_time)))) ? entries : null;
  } catch { return null; }
};

function RulesEditor({ data, busy, conflict, onSave, onCancel }) {
  const [rules, setRules] = useState(() => copy(data.rules));
  const [defaults, setDefaults] = useState(false);
  const names = Object.fromEntries(data.shows.map(s => [s.key, s.name]));
  const update = (key, values) => setRules(old => ({ ...old, shows: old.shows.map(s => s.key === key ? { ...s, ...values } : s) }));
  const invalid = rules.shows.some(s => !Number.isInteger(s.count) || s.count < 0 || s.count > 31 || !Number.isInteger(s.gap) || s.gap < 1 || s.gap > 31);
  return <form onSubmit={e => { e.preventDefault(); if (!invalid && !busy && !conflict) onSave(rules, defaults, data); }}>
    <p className="repertoire-note">Правила на {data.month}. Уже настроенные месяцы сохраняют свои параметры.</p>
    <fieldset disabled={busy || conflict} className="repertoire-fieldset">
      {rules.shows.map(rule => <div className="repertoire-rule" key={rule.key}>
        <div className="repertoire-row"><strong>{names[rule.key] || rule.key}</strong>
          <div className="repertoire-stepper">
            <button type="button" className="btn btn-secondary" aria-label={`Меньше показов: ${names[rule.key]}`} disabled={rule.count <= 0} onClick={() => update(rule.key, { count: rule.count - 1 })}>−</button>
            <input className="form-input" type="number" min="0" max="31" required aria-label={`Показов: ${names[rule.key]}`} value={rule.count} onChange={e => update(rule.key, { count: e.target.value === '' ? '' : Number(e.target.value) })} />
            <button type="button" className="btn btn-secondary" aria-label={`Больше показов: ${names[rule.key]}`} disabled={rule.count >= 31} onClick={() => update(rule.key, { count: Number(rule.count) + 1 })}>+</button>
          </div>
        </div>
        <p className="repertoire-note">{rule.weekdays.length === 7 ? 'Любые дни' : rule.weekdays.map(d => DAYS[d]).join(', ')} · {rule.spread ? `Разнос от ${rule.gap} дней` : 'Без разноса'}</p>
        <details><summary>Настроить правила</summary>
          <label className="repertoire-field">Формат<select className="select-input" aria-label={`Формат: ${names[rule.key]}`} value={rule.format || 'small'} onChange={e => {
            const format = e.target.value;
            const days = format === 'large' ? rule.weekdays.filter(d => d >= 4) : rule.weekdays;
            update(rule.key, { format, weekdays: days.length ? days : [4, 5, 6] });
          }}><option value="small">Маленький</option><option value="large">Большой</option></select></label>
          <div className="repertoire-days" aria-label={`Дни: ${names[rule.key]}`}>{DAYS.map((day, index) => <button type="button" className="btn btn-secondary" key={day} aria-pressed={rule.weekdays.includes(index)}
            disabled={rule.format === 'large' && index < 4}
            onClick={() => { const days = rule.weekdays.includes(index) ? rule.weekdays.filter(d => d !== index) : [...rule.weekdays, index].sort(); if (days.length) update(rule.key, { weekdays: days }); }}>{day}</button>)}</div>
          <p className="repertoire-note">{rule.format === 'large' ? 'Начало: пт–сб — 19:00, вс — 18:00.' : 'Начало: пн–чт — 20:00, пт–сб — 19:00, вс — 18:00.'} Время отдельного показа можно изменить в его карточке.</p>
          <label className="repertoire-check"><input type="checkbox" checked={rule.spread} onChange={e => update(rule.key, { spread: e.target.checked })} />Разносить показы по месяцу</label>
          <label className="repertoire-field">Желаемый интервал, дней<input className="form-input" type="number" min="1" max="31" required disabled={!rule.spread} value={rule.gap} onChange={e => update(rule.key, { gap: e.target.value === '' ? '' : Number(e.target.value) })} /></label>
          <label className="repertoire-field">Планировать начиная с<input className="form-input" type="date" value={rule.start || ''} onChange={e => update(rule.key, { start: e.target.value || null })} /></label>
          <p className="repertoire-note">Близкие даты допустимы, но ниже по приоритету. При одном показе разнос не влияет на расчёт.</p>
        </details>
      </div>)}
      <div className="repertoire-rule"><strong>Нагрузка актёров</strong>
        <label className="repertoire-field">Игровых дней подряд<input type="number" className="form-input" min="2" max="7" required value={rules.streak} onChange={e => setRules(old => ({ ...old, streak: e.target.value === '' ? '' : Number(e.target.value) }))} /></label>
        <label className="repertoire-field">Если порог достигнут<select className="select-input" value={rules.load_mode} onChange={e => setRules(old => ({ ...old, load_mode: e.target.value }))}>
          <option value="prefer">Понижать приоритет</option><option value="forbid">Запретить</option><option value="ignore">Не учитывать</option>
        </select></label>
        <p className="repertoire-note">Учитываются показы разных спектаклей и соседние месяцы. Репетиции не входят в нагрузку.</p>
      </div>
      <label className="repertoire-check"><input type="checkbox" checked={defaults} onChange={e => setDefaults(e.target.checked)} />Использовать и для новых месяцев</label>
    </fieldset>
    <div className="repertoire-actions"><button className="btn btn-primary" type="submit" disabled={busy || conflict || invalid}>{busy ? 'Сохраняем…' : 'Сохранить параметры'}</button><button type="button" className="btn btn-secondary" disabled={busy} onClick={onCancel}>{conflict ? 'Загрузить актуальные параметры' : 'Отмена'}</button></div>
  </form>;
}

function Diagnostics({ data, variant }) {
  const missingKeys = new Set(variant?.missing.map(s => s.key) || data.rules.shows.filter(s => s.count > 0).map(s => s.key));
  const allocated = Object.fromEntries((variant?.entries || []).map(e => [e.date, e]));
  return <details className="repertoire-diagnostics"><summary>Почему не собирается полный план</summary>
    {data.diagnostics.filter(s => missingKeys.has(s.key)).map(show => {
      const counts = {};
      show.dates.filter(d => d.reason).forEach(d => { counts[d.reason] = (counts[d.reason] || 0) + 1; });
      return <div className="repertoire-rule" key={show.key}><strong>{show.name}</strong>
        <p>Подходящих свободных дат: {show.ready_dates.length}.</p>
        {show.ready_dates.length > 0 && <p className="repertoire-note">{show.ready_dates.map(prettyDate).join('; ')}. Эти даты могут требоваться другим спектаклям; на день планируется один показ. Также учитываются закрепления и запрет нагрузки, если он включён.</p>}
        {show.ready_dates.filter(day => allocated[day] && allocated[day].key !== show.key).map(day => <p className="repertoire-note" key={day}>{prettyDate(day)}: в этом варианте стоит {allocated[day].name}.</p>)}
        {Object.entries(counts).map(([reason, count]) => <p className="repertoire-note" key={reason}>{reason}: {count} дн.</p>)}
        {!show.dates.length && <p className="repertoire-note">Нет доступных данных о ролях или датах этого спектакля.</p>}
        <details><summary>Проверка по датам и ролям</summary>{show.dates.map(day => <details key={day.date} className="repertoire-diagnostic-date"><summary>{prettyDate(day.date)}{day.start_time && `, ${day.start_time.slice(11, 16)}`} · {day.reason || 'Состав собирается'}</summary>
          {day.roles.map(role => <p className="repertoire-note" key={role.name}><strong>{role.name}: </strong>{role.actors.map(a => `${a.name} — ${a.reason}`).join('; ') || 'Нет исполнителей'}</p>)}
        </details>)}</details>
      </div>;
    })}
  </details>;
}

export default function RepertoirePlan({ month, dataVersion, userId, isSuperAdmin = false, onCastSaved }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState(null);
  const [conflict, setConflict] = useState(false);
  const [selected, setSelected] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const [share, setShare] = useState(null);
  const [publish, setPublish] = useState(null);
  const [focusDate, setFocusDate] = useState(null);
  const [draftPending, setDraftPending] = useState(false);
  const [draftError, setDraftError] = useState('');
  const storageKey = userId ? `foshoo:repertoire-draft:${userId}:${month}` : null;
  const [initialDraft] = useState(() => readDraft(storageKey, month));
  const draft = useRef(initialDraft);
  const [storageError, setStorageError] = useState(false);
  const forgetDraft = useCallback(() => { if (storageKey) { try { localStorage.removeItem(storageKey); setStorageError(false); } catch { setStorageError(true); } } }, [storageKey]);
  const selectedId = useRef(null);
  const refreshNow = () => setRefresh(n => n + 1);
  useEffect(() => {
    let active = true, timer, inFlight = false, calculating = false, searching = false;
    const load = async () => {
      if (inFlight || document.hidden) return;
      inFlight = true;
      let selectionChanged = false;
      try {
        const requestedSelected = selectedId.current;
        const { data: result } = await client.get('/api/planning/repertoire', { params: { month, ...(requestedSelected ? { selected: requestedSelected } : {}) } });
        if (!active) return;
        if (!draft.current && requestedSelected !== selectedId.current) { selectionChanged = true; return; }
        if (result.month !== month || !Array.isArray(result.variants)) throw new Error('Invalid planning response');
        if (result.locked) { draft.current = null; forgetDraft(); }
        searching = !result.complete && !draft.current;
        let next = result.selected_variant || result.variants.find(v => v.id === selectedId.current) || result.variants[0] || null;
        if (draft.current) {
          setDraftPending(true);
          setData(result);
          let reviewed;
          try {
            ({ data: reviewed } = await client.post('/api/planning/repertoire/draft', { month, entries: draft.current,
              expected_fingerprint: result.fingerprint, expected_revision: result.revision }));
          } catch (e) {
            if (!active) return;
            if (e.response?.status !== 409) throw e;
            calculating = false; setDraftPending(false); setDraftError(message(e)); setError(''); return;
          }
          if (!active) return;
          calculating = reviewed.status === 'calculating'; setDraftPending(calculating);
          if (calculating) { setError(''); return; }
          next = reviewed.variant;
          if (storageKey) { try { localStorage.setItem(storageKey, JSON.stringify(draft.current)); setStorageError(false); } catch { setStorageError(true); } }
        } else { calculating = false; setDraftPending(false); }
        setDraftError('');
        setData(result); setError('');
        setSelected(next);
        if (selectedId.current && next?.id !== selectedId.current) selectedId.current = null;
      } catch (e) { if (active) { calculating = false; searching = false; setDraftPending(false); setError(message(e)); } }
      finally {
        inFlight = false;
        if (active) {
          setLoading(false);
          // Recheck a choice made during the request without blocking the displayed plan.
          if (selectionChanged) load();
          else timer = setTimeout(load, calculating || searching ? 1000 : 30_000);
        }
      }
    };
    const focus = () => { clearTimeout(timer); load(); };
    // Only initial/explicit refreshes invalidate the current plan; polling stays in the background.
    setLoading(true);
    load(); window.addEventListener('focus', focus); document.addEventListener('visibilitychange', focus);
    return () => { active = false; clearTimeout(timer); window.removeEventListener('focus', focus); document.removeEventListener('visibilitychange', focus); };
  }, [month, refresh, dataVersion, storageKey, forgetDraft]);

  const save = async (rules, useAsDefault, base = data) => {
    if (busy) return;
    setBusy(true); setError('');
    try {
      await client.put('/api/planning/repertoire', { month, rules, expected_revision: base.revision, expected_defaults_revision: base.defaults_revision, use_as_default: useAsDefault });
      setEditor(null); setConflict(false); selectedId.current = null; if (!draft.current) setSelected(null); refreshNow();
    } catch (e) { setError(message(e)); if (e.response?.status === 409) setConflict(true); }
    finally { setBusy(false); }
  };
  const toggleAffiche = async () => {
    if (busy || loading || !isSuperAdmin) return;
    setBusy(true); setError('');
    try {
      if (data.locked || data.rules.pins.length) {
        await client.post('/api/planning/repertoire/unlock', { month, expected_revision: data.revision });
        draft.current = selected ? selected.entries.filter(e => !e.fixed).map(draftEntry) : null;
      } else {
        setShare(null); setPublish({ data: copy(data), variant: copy(selected) });
        return;
      }
      forgetDraft(); setShare(null); selectedId.current = null; setDraftError(''); refreshNow();
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  };
  const totals = selected?.entries.reduce((map, item) => ({ ...map, [item.key]: (map[item.key] || 0) + 1 }), {}) || {};
  const names = Object.fromEntries((data?.shows || []).map(s => [s.key, s.name]));
  const resetDraft = () => { draft.current = null; forgetDraft(); setDraftPending(false); setDraftError(''); setFocusDate(null); setShare(null); selectedId.current = null; refreshNow(); };
  const replaceShow = (day, key, startTime) => {
    if (busy || loading || error || draftPending || data.locked) return;
    const base = draft.current || (selected?.entries || []).filter(e => !e.fixed).map(draftEntry);
    draft.current = [...base.filter(e => e.day !== day), ...(key ? [{ day, key, ...(startTime ? { start_time: startTime } : {}) }] : [])];
    if (!key) {
      const entries = selected.entries.filter(e => e.date !== day);
      const counts = Object.fromEntries(data.rules.shows.map(s => [s.key, entries.filter(e => e.key === s.key).length]));
      setSelected({ ...selected, manual: true, entries, count: data.rules.shows.reduce((n, s) => n + Math.min(s.count, counts[s.key]), 0),
        missing: data.rules.shows.filter(s => counts[s.key] < s.count).map(s => ({ key: s.key, name: names[s.key], count: s.count - counts[s.key] })) });
    }
    setFocusDate(day); setShare(null); setDraftPending(true); selectedId.current = null; refreshNow();
  };
  const unverified = Boolean(error || draftError || data?.lock_error) || draftPending || data?.lock_pending || !!data?.publication;
  const stale = unverified || busy || loading;
  const editingDisabled = Boolean(error) || busy || loading || draftPending || data?.locked || !!data?.publication;
  return <section className="repertoire-plan" aria-labelledby="repertoire-title">
    <div className="repertoire-row"><div><h2 id="repertoire-title">План афиши</h2><p className="repertoire-note">По ответам участников и составам</p></div>
      {data && !editor && <button className="btn btn-secondary" onClick={() => { setEditor(copy(data)); setConflict(false); }} disabled={busy || data.locked || !!data.publication}>Параметры</button>}
    </div>
    {error && <div className="alert alert-error" role="alert">{error} {data && 'Показаны последние полученные данные.'}<button className="btn btn-secondary" onClick={() => { setConflict(false); refreshNow(); }} disabled={busy}>Обновить предложения</button></div>}
    {loading && !data && <p role="status">Подбираем расписание…</p>}
    {editor ? <RulesEditor data={editor} busy={busy} conflict={conflict} onSave={save} onCancel={() => { setEditor(null); setConflict(false); refreshNow(); }} /> : data && <>
      <div className="repertoire-score" aria-live="polite"><strong>{selected?.manual ? selected.count : data.maximum ?? '…'} из {data.target}</strong><span>{data.maximum === null && !selected?.manual ? 'ищем подходящие показы' : 'показов по плану'}</span></div>
      {draft.current && <div className="repertoire-manual"><p>{draftPending ? 'Проверяем замену и нагрузку…' : error || draftError ? 'Ручные изменения требуют проверки.' : 'Ручной вариант — остальные даты сохранены.'}</p><button type="button" className="btn btn-secondary" onClick={resetDraft} disabled={busy}>Отменить ручные изменения</button></div>}
      {draft.current && storageKey && !draftPending && !error && !draftError && <p className="repertoire-note">{storageError ? 'Браузер не сохранил черновик. Он доступен, пока открыт этот экран.' : 'Ручной черновик сохранён на этом устройстве для вашего аккаунта и месяца.'}</p>}
      {!data.locked && <p className="repertoire-note">До пяти вариантов с разными датами и спектаклями. {data.complete ? 'Подбор завершён.' : 'Подбираем лучшие варианты…'}
        {!data.complete && <button className="btn btn-secondary" disabled={busy} onClick={refreshNow}>Обновить подбор</button>}</p>}
      {selected?.manual && <p className="repertoire-note">Счётчики сравнивают ручной вариант с параметрами месяца. Остальные даты не переставляются.</p>}
      <div className="repertoire-totals">{data.rules.shows.filter(s => s.count > 0 || totals[s.key]).map(s => <span className={selected && (totals[s.key] || 0) < s.count ? 'repertoire-shortfall' : ''} key={s.key}>{names[s.key] || s.key} {totals[s.key] || 0}/{s.count}</span>)}</div>
      {data.warnings.map(w => <p className="planning-warning" key={w}>{w}</p>)}
      {data.pin_errors.map(w => <p className="planning-warning" role="alert" key={w}>{w}</p>)}
      {(selected || data.locked || data.rules.pins.length > 0) && <div className="repertoire-affiche">
        {isSuperAdmin && <button type="button" className="btn btn-secondary" disabled={data.locked || data.rules.pins.length ? busy || loading : stale || !selected}
          onClick={toggleAffiche}>{data.locked || data.rules.pins.length ? 'Снять закрепление' : 'Закрепить афишу месяца'}</button>}
        <p className="repertoire-note">{data.locked ? 'Афиша месяца закреплена и сохранена для всех администраторов. Для правок снимите закрепление.' : data.rules.pins.length ? 'В этом месяце остались прежние закрепления отдельных дат. Снимите их, чтобы редактировать афишу целиком.' : 'Закрепление сохранит всю афишу, включая пустые даты.'} {data.locked ? 'Снятие закрепления не отменяет созданные и изменённые события календаря.' : 'После подтверждения репетиции станут показами, а на свободные даты добавятся новые события.'} {!isSuperAdmin && 'Закрепление доступно только суперадминистратору.'}</p>
        {data.lock_pending && <p role="status">Проверяем актуальные ответы для закреплённой афиши…</p>}
        {data.lock_error && <p className="planning-warning" role="alert">{data.lock_error} Сохранённая афиша оставлена без изменений; требуется проверка.</p>}
      </div>}
      {data.publication && <div className="planning-warning" role="status">Применение афиши не завершено. Сохранено: {data.publication.done} из {data.publication.actions.length}.
        {isSuperAdmin && <button type="button" className="btn btn-primary" onClick={() => setPublish({ data: copy(data), publication: copy(data.publication) })}>Проверить и продолжить сохранение</button>}
      </div>}
      {draftError && <p className="planning-warning" role="alert">{draftError} Можно удалить или заменить проблемный показ.</p>}
      {!data.locked && <RepertoireAlternatives variants={data.variants} selected={selected} recommendedId={data.recommended_id} complete={data.complete} disabled={stale}
        onSelect={v => { setFocusDate(null); setShare(null); setSelected(v); selectedId.current = v.id; }} />}
      {selected && <>
        {selected.excess?.length > 0 && <p className="planning-warning">Сверх плана: {selected.excess.map(s => `${s.name} — ${s.count}`).join('; ')}. Всего в варианте {selected.entries.length} показов.</p>}
        {selected.missing.length > 0 && <div className="planning-warning">Не хватает: {selected.missing.map(s => `${s.name} — ${s.count}`).join('; ')}. Остальные показатели показаны выше.</div>}
        {selected.spread_warnings.map((w, i) => <p className="planning-warning" key={`gap-${i}`}>{w.name}: {w.dates.map(prettyDate).join(' → ')} · {w.gap} дн. между показами, желательно {w.desired}.{w.same_part && ' Одна часть месяца.'}</p>)}
        {selected.load_warnings.map((w, i) => <p className="planning-warning" key={`load-${i}`}>{w.actor}: {w.dates.length} игровых дня подряд · {w.dates.map(prettyDate).join(' → ')}</p>)}
        {!unverified && !selected.spread_score && !selected.load_warnings.length && <p className="repertoire-good">✓ Пожелания по разносу и нагрузке соблюдены для известных составов</p>}
        <RepertoireCalendar key={`${month}:${selected.id}`} month={month} focusDate={focusDate} entries={selected.entries} pins={data.rules.pins} onSelectDay={() => { if (!selected.manual) selectedId.current = selected.id; }}
          renderDay={day => <RepertoireDayOptions key={day} month={month} day={day} data={data} entries={selected.entries} disabled={editingDisabled} onReplace={replaceShow} onRefresh={refreshNow} onCastSaved={onCastSaved} />} renderEntry={entry => {
          const pinned = data.rules.pins.some(p => p.day === entry.date && p.key === entry.key);
          return <div className="repertoire-date" key={`${entry.date}:${entry.key}`}><div className="repertoire-row"><div><span className="repertoire-date-label">{prettyDate(entry.date)}{entry.start_time && ` · ${entry.start_time.slice(11, 16)}`}</span><strong>{entry.name}</strong><small>{entry.fixed ? 'Уже в расписании' : data.locked ? 'В закреплённой афише' : pinned ? 'Закреплено в плане' : draftError ? 'Требует проверки' : 'В плане'}</small>{entry.rehearsals?.length > 0 && <small>Репетиционный слот</small>}</div>
            {!entry.fixed && <button type="button" className="btn btn-secondary" aria-label={`Удалить ${entry.name}, ${entry.date}`} disabled={editingDisabled || pinned} onClick={() => replaceShow(entry.date, null)}>Удалить из афиши</button>}
          </div>{!entry.fixed && <RepertoireShowTime key={`${entry.date}:${entry.key}:${entry.start_time}`} entry={entry} disabled={editingDisabled}
            onChange={value => replaceShow(entry.date, entry.key, value)} />}</div>;
        }} />
        <button type="button" className="btn btn-primary repertoire-share-button" disabled={stale || !selected.entries.length} onClick={() => setShare({ data: copy(data), variant: copy(selected) })}>Отправить в чат</button>
      </>}
      {!selected && <RepertoireCalendar month={month} focusDate={focusDate} entries={[]} pins={data.rules.pins}
        renderDay={day => <RepertoireDayOptions key={day} month={month} day={day} data={data} entries={[]} disabled={editingDisabled} onReplace={replaceShow} onRefresh={refreshNow} onCastSaved={onCastSaved} />} />}
      {(data.maximum === null || data.maximum < data.target || selected?.missing.length > 0) && <Diagnostics data={data} variant={selected} />}
      {data.complete && !data.total_variants && !data.pin_errors.length && <p className="planning-warning">Нет допустимого варианта с закреплёнными датами и текущими ограничениями нагрузки. Проверьте параметры.</p>}
      <p className="repertoire-note">Один показ в день. Репетиционная дата подходит для любого спектакля с полным составом. Прочие события мешают только при пересечении по времени. Свободное время не подтверждает бронь зала.</p>
      <p className="repertoire-note">{data.locked ? 'Закреплённая афиша' : 'Черновик'} · обновлено {new Intl.DateTimeFormat('ru', { hour: '2-digit', minute: '2-digit', timeZone: data.timezone }).format(new Date(data.checked_at))}. Ответы проверяются каждые 30 секунд, пока экран открыт.</p>
    </>}
    {publish && isSuperAdmin && <RepertoirePublish {...publish} onClose={() => { setPublish(null); refreshNow(); }} onApplied={() => { draft.current = null; forgetDraft(); setPublish(null); setShare(null); selectedId.current = null; refreshNow(); }} />}
    {share && <RepertoireShare key={`${share.data.search_id}:${share.variant.id}`} data={share.data} variant={share.variant} onClose={() => setShare(null)} />}
  </section>;
}
