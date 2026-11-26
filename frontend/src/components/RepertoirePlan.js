import React, { useEffect, useRef, useState } from 'react';
import client from '../api/client';
import './RepertoirePlan.css';

const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const prettyDate = day => new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short', weekday: 'short', timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`));
const message = e => typeof e.response?.data?.detail === 'string' ? e.response.data.detail : 'Не удалось обновить план. Проверьте соединение и повторите.';
const copy = value => JSON.parse(JSON.stringify(value));

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
          <div className="repertoire-days" aria-label={`Дни: ${names[rule.key]}`}>{DAYS.map((day, index) => <button type="button" className="btn btn-secondary" key={day} aria-pressed={rule.weekdays.includes(index)}
            onClick={() => { const days = rule.weekdays.includes(index) ? rule.weekdays.filter(d => d !== index) : [...rule.weekdays, index].sort(); if (days.length) update(rule.key, { weekdays: days }); }}>{day}</button>)}</div>
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
        <details><summary>Проверка по датам и ролям</summary>{show.dates.map(day => <details key={day.date} className="repertoire-diagnostic-date"><summary>{prettyDate(day.date)} · {day.reason || 'Состав собирается'}</summary>
          {day.roles.map(role => <p className="repertoire-note" key={role.name}><strong>{role.name}: </strong>{role.actors.map(a => `${a.name} — ${a.reason}`).join('; ') || 'Нет исполнителей'}</p>)}
        </details>)}</details>
      </div>;
    })}
  </details>;
}

export default function RepertoirePlan({ month, dataVersion, onPrepared }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState(null);
  const [conflict, setConflict] = useState(false);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const selectedId = useRef(null);
  const refreshNow = () => setRefresh(n => n + 1);
  useEffect(() => {
    let active = true, timer, inFlight = false;
    const load = async () => {
      if (inFlight || document.hidden) return;
      inFlight = true;
      setLoading(true);
      try {
        const { data: result } = await client.get('/api/planning/repertoire', { params: { month, page, ...(selectedId.current ? { selected: selectedId.current } : {}) } });
        if (!active) return;
        if (result.month !== month || !Array.isArray(result.variants)) throw new Error('Invalid planning response');
        setData(result); setError('');
        const next = result.selected_variant || result.variants.find(v => v.id === selectedId.current) || result.variants[0] || null;
        setSelected(next);
        if (selectedId.current && next?.id !== selectedId.current) selectedId.current = null;
      } catch (e) { if (active) setError(message(e)); }
      finally {
        inFlight = false;
        if (active) { setLoading(false); timer = setTimeout(load, 30_000); }
      }
    };
    const focus = () => { clearTimeout(timer); load(); };
    load(); window.addEventListener('focus', focus); document.addEventListener('visibilitychange', focus);
    return () => { active = false; clearTimeout(timer); window.removeEventListener('focus', focus); document.removeEventListener('visibilitychange', focus); };
  }, [month, page, refresh, dataVersion]);

  const save = async (rules, useAsDefault, base = data) => {
    if (busy) return;
    setBusy(true); setError('');
    try {
      await client.put('/api/planning/repertoire', { month, rules, expected_revision: base.revision, expected_defaults_revision: base.defaults_revision, use_as_default: useAsDefault });
      setEditor(null); setConflict(false); selectedId.current = null; setSelected(null); setPage(0); refreshNow();
    } catch (e) { setError(message(e)); if (e.response?.status === 409) setConflict(true); }
    finally { setBusy(false); }
  };
  const pin = entry => {
    const exists = data.rules.pins.some(p => p.day === entry.date && p.key === entry.key);
    const pins = data.rules.pins.filter(p => p.day !== entry.date);
    if (!exists) pins.push({ day: entry.date, key: entry.key });
    save({ ...data.rules, pins }, false);
  };
  const prepare = async entry => {
    if (busy || error) return;
    setBusy(true);
    try {
      const { data: result } = await client.post('/api/planning/repertoire/prepare', { month, day: entry.date, key: entry.key, expected_fingerprint: data.fingerprint, expected_revision: data.revision });
      onPrepared(result, entry.cast);
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  };
  const totals = selected?.entries.reduce((map, item) => ({ ...map, [item.key]: (map[item.key] || 0) + 1 }), {}) || {};
  const names = Object.fromEntries((data?.shows || []).map(s => [s.key, s.name]));
  const choosePage = next => { selectedId.current = null; setSelected(null); setPage(next); setLoading(true); };
  const stale = Boolean(error) || busy || loading;
  return <section className="repertoire-plan" aria-labelledby="repertoire-title">
    <div className="repertoire-row"><div><h2 id="repertoire-title">План афиши</h2><p className="repertoire-note">По ответам участников и составам</p></div>
      {data && !editor && <button className="btn btn-secondary" onClick={() => { setEditor(copy(data)); setConflict(false); }} disabled={busy}>Параметры</button>}
    </div>
    {error && <div className="alert alert-error" role="alert">{error} {data && 'Показаны последние полученные данные.'}<button className="btn btn-secondary" onClick={() => { setConflict(false); refreshNow(); }} disabled={busy}>Обновить предложения</button></div>}
    {loading && !data && <p role="status">Подбираем расписание…</p>}
    {editor ? <RulesEditor data={editor} busy={busy} conflict={conflict} onSave={save} onCancel={() => { setEditor(null); setConflict(false); refreshNow(); }} /> : data && <>
      <div className="repertoire-score" aria-live="polite"><strong>{data.maximum ?? '…'} из {data.target}</strong><span>{data.maximum === null ? 'ищем подходящие показы' : 'показов'}</span></div>
      <p className="repertoire-note">{data.complete ? `Перебор завершён. Вариантов: ${data.total_variants}.` : `Найдено вариантов: ${data.total_variants}. Перебор продолжается — порядок ещё может измениться.`}
        {!data.complete && <button className="btn btn-secondary" disabled={busy} onClick={refreshNow}>Продолжить поиск</button>}</p>
      <p className="repertoire-note">{data.maximum !== null && data.maximum < data.target ? 'Максимум по обязательным ограничениям. Ниже — все варианты с таким числом показов.' : 'Близкие показы и нагрузка снижают приоритет, но не скрывают допустимые варианты.'}</p>
      <div className="repertoire-totals">{data.rules.shows.filter(s => s.count > 0 || totals[s.key]).map(s => <span className={selected && (totals[s.key] || 0) < s.count ? 'repertoire-shortfall' : ''} key={s.key}>{names[s.key] || s.key} {totals[s.key] || 0}/{s.count}</span>)}</div>
      {data.warnings.map(w => <p className="planning-warning" key={w}>{w}</p>)}
      {data.pin_errors.map(w => <p className="planning-warning" role="alert" key={w}>{w}</p>)}
      {data.rules.pins.length > 0 && <details><summary>Закреплённые даты ({data.rules.pins.length})</summary>{data.rules.pins.map(p => <div className="repertoire-row" key={p.day}><span>{prettyDate(p.day)} · {names[p.key] || p.key}</span><button className="btn btn-secondary" disabled={stale} onClick={() => save({ ...data.rules, pins: data.rules.pins.filter(x => x.day !== p.day) }, false)}>Снять закрепление</button></div>)}</details>}
      {data.total_variants > 0 && <>
        <label className="repertoire-variant-label">Вариант расписания<select className="select-input" aria-label="Вариант расписания" value={data.variants.some(v => v.id === selected?.id) ? selected.id : ''} onChange={e => { const v = data.variants.find(item => item.id === e.target.value); setSelected(v); selectedId.current = v.id; }}>
          {!data.variants.some(v => v.id === selected?.id) && <option value="">Выбранный вариант на другой странице</option>}
          {data.variants.map((v, i) => <option value={v.id} key={v.id}>{data.page * data.page_size + i + 1}. {v.count}/{data.target}{v.missing.length ? ` · Не хватает: ${v.missing.map(s => `${s.name} ×${s.count}`).join(', ')}` : ''}{v.load_score || v.spread_score ? ' · Есть отклонения' : ' · Предпочтения соблюдены'}</option>)}
        </select></label>
        {data.total_variants > data.page_size && <div className="repertoire-pages"><button className="btn btn-secondary" disabled={data.page === 0 || busy} onClick={() => choosePage(data.page - 1)}>←</button><span>Страница {data.page + 1} из {Math.ceil(data.total_variants / data.page_size)}</span><button className="btn btn-secondary" disabled={(data.page + 1) * data.page_size >= data.total_variants || busy} onClick={() => choosePage(data.page + 1)}>→</button></div>}
      </>}
      {selected && <>
        {selected.missing.length > 0 && <div className="planning-warning">Не хватает: {selected.missing.map(s => `${s.name} — ${s.count}`).join('; ')}. Остальные показатели показаны выше.</div>}
        {selected.spread_warnings.map((w, i) => <p className="planning-warning" key={`gap-${i}`}>{w.name}: {w.dates.map(prettyDate).join(' → ')} · {w.gap} дн. между показами, желательно {w.desired}.{w.same_part && ' Одна часть месяца.'}</p>)}
        {selected.load_warnings.map((w, i) => <p className="planning-warning" key={`load-${i}`}>{w.actor}: {w.dates.length} игровых дня подряд · {w.dates.map(prettyDate).join(' → ')}</p>)}
        {!selected.spread_score && !selected.load_warnings.length && <p className="repertoire-good">✓ Пожелания по разносу и нагрузке соблюдены для известных составов</p>}
        <div className="repertoire-dates">{selected.entries.map(entry => {
          const pinned = data.rules.pins.some(p => p.day === entry.date && p.key === entry.key);
          return <div className="repertoire-date" key={`${entry.date}:${entry.key}`}><div className="repertoire-row"><div><span className="repertoire-date-label">{prettyDate(entry.date)}</span><strong>{entry.name}</strong><small>{entry.fixed ? 'Уже в расписании' : pinned ? 'Закреплено в плане' : 'Состав собран'}</small></div>
            {!entry.fixed && <button className="btn btn-secondary" aria-label={`${pinned ? 'Открепить' : 'Закрепить'} ${entry.name}, ${entry.date}`} aria-pressed={pinned} disabled={stale} onClick={() => pin(entry)}>{pinned ? 'Закреплено' : 'Закрепить'}</button>}
          </div><details><summary>Состав и назначение</summary>{Object.entries(entry.cast).map(([role, actor]) => <p key={role} className="repertoire-note">{role} — {actor}</p>)}
            {!Object.keys(entry.cast).length && <p className="repertoire-note">Состав не указан; нагрузка этого показа не проверена.</p>}
            {!entry.fixed && <><p className="repertoire-note">Откроется форма времени, места и состава. При необходимости добавится пустая дата в график; событие создаётся после подтверждения формы.</p><button className="btn btn-primary" disabled={stale} onClick={() => prepare(entry)}>Перейти к назначению</button></>}
          </details></div>;
        })}</div>
      </>}
      {(data.maximum === null || data.maximum < data.target) && <Diagnostics data={data} variant={selected} />}
      {data.complete && !data.total_variants && !data.pin_errors.length && <p className="planning-warning">Нет допустимого варианта с закреплёнными датами и текущими ограничениями нагрузки. Проверьте параметры.</p>}
      <p className="repertoire-note">Один показ в день. Даты с событиями календаря заняты. Свободная дата не подтверждает бронь зала.</p>
      <p className="repertoire-note">Черновик · обновлено {new Intl.DateTimeFormat('ru', { hour: '2-digit', minute: '2-digit', timeZone: data.timezone }).format(new Date(data.checked_at))}. Ответы проверяются каждые 30 секунд, пока экран открыт.</p>
    </>}
  </section>;
}
