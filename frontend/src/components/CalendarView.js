import React, { useState, useEffect, useCallback, useRef } from 'react';
import * as calendarApi from '../api/calendar';
import client from '../api/client';
import PlanningView from './PlanningView';
import { calendarFilters, calendarDetails, getEventDetailKey, getEventColor, matchesCalendarFilter } from './calendarPresentation';
import './CalendarView.css';

const MONTHS = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
const DAYS   = ['вс','пн','вт','ср','чт','пт','сб'];

function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

function toLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const EMPTY_FORM = { title: '', start_time: '', end_time: '', location: '', description: '' };

const MONTHS_FULL = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const DOW = ['пн','вт','ср','чт','пт','сб','вс'];

const HOUR_START = 9;
const HOUR_END   = 24;
const HOUR_H     = 18;
const HEADER_H   = 42;
const LABEL_W    = 28;

function WeekCalendar({ events, now, onEventClick, onSlotClick }) {
  const [weekOffset, setWeekOffset] = useState(0);
  const [tooltip, setTooltip] = useState(null);

  const weekStart = (() => {
    const d = new Date();
    const dow = d.getDay();
    d.setDate(d.getDate() - (dow === 0 ? 6 : dow - 1) + weekOffset * 7);
    d.setHours(0, 0, 0, 0);
    return d;
  })();

  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + i);
    return d;
  });

  const today = new Date(); today.setHours(0, 0, 0, 0);
  const totalW = window.innerWidth - 48;
  const colW = (totalW - LABEL_W) / 7;
  const chartH = (HOUR_END - HOUR_START) * HOUR_H;
  const svgH = HEADER_H + chartH;

  const timeToY = (dt, isEnd = false) => {
    let raw = dt.getHours() + dt.getMinutes() / 60;
    if (isEnd && raw === 0) raw = 24;
    const h = Math.max(HOUR_START, Math.min(HOUR_END, raw));
    return HEADER_H + (h - HOUR_START) * HOUR_H;
  };

  const monthLabel = (() => {
    const f = MONTHS_FULL[days[0].getMonth()], l = MONTHS_FULL[days[6].getMonth()], y = days[6].getFullYear();
    return f === l ? `${f} ${y}` : `${f} — ${l} ${y}`;
  })();

  const fmt = dt => `${String(dt.getHours()).padStart(2,'0')}:${String(dt.getMinutes()).padStart(2,'0')}`;

  const handleSvgClick = (evt) => {
    if (!onSlotClick) return;
    const rect = evt.currentTarget.getBoundingClientRect();
    const x = evt.clientX - rect.left;
    const y = evt.clientY - rect.top;
    if (x < LABEL_W || y < HEADER_H) return;
    const dayIdx = Math.floor((x - LABEL_W) / colW);
    if (dayIdx < 0 || dayIdx >= 7) return;
    const hour = Math.min(HOUR_START + Math.floor((y - HEADER_H) / HOUR_H), HOUR_END - 1);
    const d = new Date(days[dayIdx]);
    d.setHours(hour, 0, 0, 0);
    onSlotClick(d);
  };

  const weekEvents = events.filter(e => {
    const d = new Date(e.start_time); d.setHours(0,0,0,0);
    return d >= days[0] && d <= days[6];
  });

  const nowY = (() => {
    const now = new Date();
    const todayIdx = days.findIndex(d => d.getTime() === today.getTime());
    if (todayIdx < 0) return null;
    const h = now.getHours() + now.getMinutes() / 60;
    if (h < HOUR_START || h > HOUR_END) return null;
    return { y: HEADER_H + (h - HOUR_START) * HOUR_H, x: LABEL_W + todayIdx * colW };
  })();

  return (
    <div className="card-white" style={{ padding: '10px 8px', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6, padding: '0 4px' }}>
        <button onClick={() => setWeekOffset(o => o - 1)} style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#555', padding: '0 4px' }}>‹</button>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#333' }}>{monthLabel}</span>
        <button onClick={() => setWeekOffset(o => o + 1)} style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#555', padding: '0 4px' }}>›</button>
      </div>
      <div style={{ position: 'relative' }}>
        {tooltip && (
          <div style={{
            position: 'absolute', zIndex: 20, pointerEvents: 'none',
            left: Math.max(0, Math.min(tooltip.x - 60, totalW - 130)),
            top: Math.max(0, tooltip.y - 44),
            background: '#111', color: '#fff', borderRadius: 6,
            padding: '4px 8px', fontSize: 11, whiteSpace: 'nowrap',
          }}>
            <div style={{ fontWeight: 600 }}>{tooltip.title}</div>
            <div style={{ color: '#ccc' }}>{tooltip.time}</div>
          </div>
        )}
        <div style={{ overflowY: 'auto', overflowX: 'hidden', maxHeight: 360 }}>
          <svg width={totalW} height={svgH} style={{ display: 'block' }} onClick={handleSvgClick}>
            {/* Column backgrounds + day headers */}
            {days.map((d, i) => {
              const isToday = d.getTime() === today.getTime();
              const isWeekend = i >= 5;
              const cx = LABEL_W + i * colW + colW / 2;
              const dowColor = isToday ? '#7C3AED' : isWeekend ? '#EF4444' : '#aaa';
              const dateColor = isToday ? '#fff' : isWeekend ? '#EF4444' : '#444';
              return (
                <g key={i}>
                  {isToday && <rect x={LABEL_W + i * colW} y={0} width={colW} height={svgH} fill="#f8f6ff" />}
                  <line x1={LABEL_W + i * colW} x2={LABEL_W + i * colW} y1={HEADER_H} y2={svgH} stroke="#f0f0f0" strokeWidth={1} />
                  <text x={cx} y={13} textAnchor="middle" fontSize={9} fill={dowColor} fontWeight={isToday ? 700 : 400}>{DOW[i]}</text>
                  {isToday
                    ? <><circle cx={cx} cy={29} r={11} fill="#7C3AED" /><text x={cx} y={33} textAnchor="middle" fontSize={12} fill="#fff" fontWeight={700}>{d.getDate()}</text></>
                    : <text x={cx} y={33} textAnchor="middle" fontSize={12} fill={dateColor}>{d.getDate()}</text>
                  }
                </g>
              );
            })}
            {/* Hour grid */}
            {Array.from({ length: HOUR_END - HOUR_START + 1 }, (_, i) => {
              const hour = HOUR_START + i;
              const y = HEADER_H + i * HOUR_H;
              return (
                <g key={hour}>
                  <line x1={LABEL_W} x2={totalW} y1={y} y2={y} stroke="#f0f0f0" strokeWidth={1} />
                  {hour % 3 === 0 && hour < HOUR_END && (
                    <text x={LABEL_W - 3} y={y + 4} textAnchor="end" fontSize={8} fill="#bbb">{hour}</text>
                  )}
                </g>
              );
            })}
            {/* Events */}
            {weekEvents.map((e, idx) => {
              const startDt = new Date(e.start_time);
              const endDt   = new Date(e.end_time);
              const dayStr  = new Date(startDt).setHours(0,0,0,0);
              const dayIdx  = days.findIndex(d => d.getTime() === dayStr);
              if (dayIdx < 0) return null;
              const y1 = timeToY(startDt);
              const y2 = timeToY(endDt, true);
              const h  = Math.max(6, y2 - y1);
              const x  = LABEL_W + dayIdx * colW + 3;
              const w  = colW - 6;
              const color = getEventColor(e);
              return (
                <rect key={idx} x={x} y={y1} width={w} height={h} rx={3}
                  fill={color} fillOpacity={endDt.getTime() <= now ? 0.35 : 0.9} style={{ cursor: 'pointer' }}
                  onMouseEnter={() => setTooltip({ title: e.title, time: `${fmt(startDt)}–${fmt(endDt)}`, x: x + w/2, y: y1 })}
                  onMouseLeave={() => setTooltip(null)}
                  onTouchStart={() => setTooltip({ title: e.title, time: `${fmt(startDt)}–${fmt(endDt)}`, x: x + w/2, y: y1 })}
                  onTouchEnd={() => setTimeout(() => setTooltip(null), 2000)}
                  onClick={(evt) => { evt.stopPropagation(); onEventClick && onEventClick(e); }}
                />
              );
            })}
            {/* Current time line */}
            {nowY && (
              <line x1={nowY.x} x2={nowY.x + colW} y1={nowY.y} y2={nowY.y} stroke="#EF4444" strokeWidth={1.5} />
            )}
          </svg>
        </div>
      </div>
    </div>
  );
}

function EventCard({ event, userId, onEdit, isAdmin, isPollable, isPast, poll, onPollAction }) {
  const start = new Date(event.start_time);
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState(null);
  const [pollShows, setPollShows] = useState(null);
  const [selectedShowId, setSelectedShowId] = useState('');
  const selectedShow = pollShows?.find(show => String(show.id) === selectedShowId);

  const handlePoll = async (showId = null) => {
    if (!userId) { setPollError('Нет userId'); return; }
    if (poll && showId === null) {
      const date = poll.created_at
        ? new Date(poll.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
        : '—';
      const confirmed = window.confirm(
        `Запустить новый опрос?\n\nПоследний был ${date}: буду ${poll.attending}, не буду ${poll.not_attending}.`
      );
      if (!confirmed) return;
    }
    try {
      setPolling(true);
      setPollError(null);
      await calendarApi.launchPoll(event.id, userId, showId);
      setPollShows(null);
      setSelectedShowId('');
      onPollAction && onPollAction();
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (detail?.code === 'show_required') {
        setPollShows(detail.shows || []);
        setSelectedShowId('');
      } else {
        setPollError(typeof detail === 'string' ? detail : detail?.message || 'Не удалось запустить опрос');
      }
    } finally {
      setPolling(false);
    }
  };

  const handlePin = async () => {
    try {
      await client.post(`/api/polls/${poll.poll_id}/pin`);
    } catch (e) {
      alert(e.response?.data?.detail || 'Ошибка закрепления');
    }
  };

  const handleDeletePoll = async () => {
    if (!window.confirm('Удалить опрос?')) return;
    try {
      await client.delete(`/api/polls/${poll.poll_id}`);
      onPollAction && onPollAction();
    } catch (e) {
      if (e.response?.status === 409) {
        if (window.confirm(e.response.data.detail + '\n\nВсё равно удалить?')) {
          await client.delete(`/api/polls/${poll.poll_id}?force=true`);
          onPollAction && onPollAction();
        }
      } else {
        alert(e.response?.data?.detail || 'Ошибка');
      }
    }
  };

  return (
    <div className="event-card" style={{ position: 'relative', opacity: isPast ? 0.5 : 1, borderLeft: `4px solid ${getEventColor(event)}` }}>
      {isAdmin && (
        <button
          onClick={() => onEdit(event)}
          style={{
            position: 'absolute', top: 10, right: 12,
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 15, color: '#bbb', padding: 0, lineHeight: 1,
          }}
        >✏️</button>
      )}
      <div className="event-date-block">
        <div className="event-date-day">{start.getDate()}</div>
        <div className="event-date-month">{MONTHS[start.getMonth()]}</div>
        <div className="event-date-dow">{DAYS[start.getDay()]}</div>
      </div>
      <div className="event-body">
        <div className="event-title" style={{ paddingRight: isAdmin ? 24 : 0 }}>{event.title}</div>
        <span className="event-type-label">{event.event_type === 'performance' ? 'Спектакль'
          : event.event_type === 'rehearsal' ? 'Репетиция' : 'Прочее'}</span>
        {(event.poll_show_name || event.show_name) && !event.title.toLowerCase().includes((event.poll_show_name || event.show_name).toLowerCase()) && (
          <div className="event-meta">{event.poll_show_name || event.show_name}</div>
        )}
        <div className="event-meta">
          {formatTime(event.start_time)} – {formatTime(event.end_time)}
          {event.location ? `  📍 ${event.location}` : ''}
          {isPast ? ' · Завершено' : ''}
        </div>
        {pollError && <div style={{ fontSize: 12, color: 'var(--danger)', marginBottom: 8 }}>{pollError}</div>}
        {pollShows !== null && (
          <div style={{ margin: '10px 0' }}>
            <label htmlFor={`poll-show-${event.id}`} style={{ display: 'block', marginBottom: 8 }}>
              Не удалось определить спектакль. Выберите его для этой репетиции:
            </label>
            {pollShows.length > 0 ? (
              <>
                <select id={`poll-show-${event.id}`} value={selectedShowId} disabled={polling}
                  onChange={e => { setSelectedShowId(e.target.value); setPollError(null); }}
                  style={{ width: '100%', marginBottom: 8 }}>
                  <option value="">Выберите спектакль</option>
                  {pollShows.map(show => (
                    <option key={show.id} value={show.id} disabled={!show.telegram_chat_id}>
                      {show.name}{show.telegram_chat_id ? '' : ' — чат не настроен'}
                    </option>
                  ))}
                </select>
                {selectedShow && (
                  <div className="event-meta" style={{ marginBottom: 8 }}>
                    Опрос и напоминания пойдут в чат «{selectedShow.chat_title || selectedShow.name}».
                  </div>
                )}
                {!pollShows.some(show => show.telegram_chat_id) && (
                  <div className="event-meta">Попросите суперадмина указать чаты в настройках «Спектакли и чаты».</div>
                )}
                <button className="btn btn-primary" disabled={polling || !selectedShow?.telegram_chat_id}
                  onClick={() => handlePoll(Number(selectedShowId))}>
                  {polling ? 'Отправляем…' : 'Отправить опрос'}
                </button>
              </>
            ) : (
              <div className="event-meta">Список спектаклей пуст. Попросите суперадмина добавить их в настройках «Спектакли и чаты».</div>
            )}
            <button className="btn btn-secondary" disabled={polling} style={{ marginLeft: 8 }}
              onClick={() => { setPollShows(null); setSelectedShowId(''); setPollError(null); }}>Отмена</button>
          </div>
        )}
        <div className="event-actions" style={{ gap: 6, alignItems: 'center' }}>
          {isAdmin && isPollable && pollShows === null && (
            <button className="btn btn-secondary" onClick={() => handlePoll()} disabled={polling} style={{ fontSize: 13, padding: '5px 10px' }}>
              {polling ? '⌛' : '🗳️ Опрос'}
            </button>
          )}
          {poll && (
            <>
              <span
                style={{ border: '2px solid #22c55e', borderRadius: 7, padding: '2px 7px', fontWeight: 700, fontSize: 13, cursor: poll.tg_link ? 'pointer' : 'default' }}
                onClick={() => poll.tg_link && (window.Telegram?.WebApp?.openLink ? window.Telegram.WebApp.openLink(poll.tg_link) : window.open(poll.tg_link, '_blank'))}
              >{poll.attending}</span>
              <span
                style={{ border: '2px solid #ef4444', borderRadius: 7, padding: '2px 7px', fontWeight: 700, fontSize: 13, cursor: poll.tg_link ? 'pointer' : 'default' }}
                onClick={() => poll.tg_link && (window.Telegram?.WebApp?.openLink ? window.Telegram.WebApp.openLink(poll.tg_link) : window.open(poll.tg_link, '_blank'))}
              >{poll.not_attending}</span>
              {poll.telegram_message_id && (
                <button onClick={handlePin} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 15, padding: '0 2px', lineHeight: 1 }}>📌</button>
              )}
              <button onClick={handleDeletePoll} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 19, color: '#ccc', padding: '0 2px', lineHeight: 1 }}>×</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function EventModal({ event, onClose, onSaved, onDeleted }) {
  const isEdit = !!event?.id;
  const eventId = event?.id;
  const [form, setForm] = useState(
    isEdit
      ? { ...EMPTY_FORM, ...event, location: event.location || '', description: event.description || '',
          start_time: toLocalInput(event.start_time), end_time: toLocalInput(event.end_time) }
      : { ...EMPTY_FORM, ...(event?.start_time ? { start_time: event.start_time, end_time: event.end_time } : {}) }
  );
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null);
  const [scope, setScope] = useState('single');
  const [editor, setEditor] = useState(null);
  const [reading, setReading] = useState(isEdit);
  const [readVersion, setReadVersion] = useState(0);
  const drafts = useRef({});
  const savingRef = useRef(false);

  useEffect(() => {
    if (!isEdit) return;
    let cancelled = false;
    setReading(true);
    setError(null);
    setEditor(null);
    const apply = data => {
      setEditor(data);
      setForm({
        title: data.title, location: data.location || '', description: data.description || '',
        start_time: data.all_day ? data.start_time : toLocalInput(data.start_time),
        end_time: data.all_day ? data.end_time : toLocalInput(data.end_time),
      });
    };
    if (drafts.current[scope]) {
      setEditor(drafts.current[scope].editor);
      setForm(drafts.current[scope].form);
      setReading(false);
    } else {
      calendarApi.getEventEditor(eventId, scope).then(({ data }) => {
        if (!cancelled) apply(data);
      }).catch(e => {
        if (!cancelled) setError(e.response?.data?.detail || 'Не удалось прочитать событие из Google Calendar');
      }).finally(() => { if (!cancelled) setReading(false); });
    }
    return () => { cancelled = true; };
  }, [eventId, isEdit, scope, readVersion]);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const changeScope = value => {
    drafts.current[scope] = { form, editor };
    setScope(value);
  };
  const reload = () => {
    delete drafts.current[scope];
    setReadVersion(value => value + 1);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (savingRef.current || reading || (isEdit && !editor)) return;
    if (!form.title || !form.start_time || !form.end_time) {
      setError('Заполните обязательные поля');
      return;
    }
    try {
      savingRef.current = true;
      setSaving(true);
      setError(null);
      const data = {
        title: form.title, location: form.location, description: form.description,
        start_time: editor?.all_day ? form.start_time : new Date(form.start_time).toISOString(),
        end_time: editor?.all_day ? form.end_time : new Date(form.end_time).toISOString(),
      };
      let result;
      if (isEdit) {
        result = await calendarApi.updateEvent(event.id, { ...data, scope, expected_etag: editor.etag });
      } else {
        result = await calendarApi.createEvent(data);
      }
      onSaved(result?.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка при сохранении');
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (scope !== 'single' || savingRef.current) return;
    if (!window.confirm('Удалить только это событие?')) return;
    try {
      setDeleting(true);
      await calendarApi.deleteEvent(event.id);
      onDeleted();
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка при удалении');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-handle" />
        <div className="modal-title">{isEdit ? 'Редактировать' : 'Новое событие'}</div>

        {error && <div role="alert" className="alert alert-error">{error}
          {isEdit && <button type="button" onClick={reload} disabled={reading || saving}>Перечитать из Google</button>}
        </div>}
        {reading && <div role="status">Читаем событие из Google Calendar…</div>}
        {editor?.is_recurring && (
          <div className="form-group">
            <label className="form-label" htmlFor="event-edit-scope">Что изменить</label>
            <select id="event-edit-scope" className="form-input" value={scope}
              disabled={reading || saving || deleting} onChange={e => changeScope(e.target.value)}>
              <option value="single">Только это событие</option>
              <option value="series">Вся серия</option>
            </select>
          </div>
        )}
        {scope === 'series' && (
          <div className="alert" role="status">
            Изменится вся серия, включая прошедшие события. Ниже указаны даты первого события серии.
            Правило повторения сохранится.
          </div>
        )}

        <form onSubmit={handleSave}>
          <fieldset disabled={reading || saving || deleting || (isEdit && !editor)} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
          <div className="form-group">
            <label className="form-label">Название *</label>
            <input className="form-input" value={form.title} onChange={e => set('title', e.target.value)} placeholder="Репетиция «Гамлет»" required />
            <div className="event-meta">Репетиция: Репетиция [Цианистый Калий] или Цианистый Калий [Реп]. Показ: название спектакля без типа или с меткой [Спект].</div>
            <div className="event-meta">Для внешнего показа укажите, например, «Фрекен Жюли [Спект]». Чат и добавление в каталог для такой метки не нужны.</div>
          </div>
          <div className="form-group">
            <label className="form-label">Начало *</label>
            <input className="form-input" type={editor?.all_day ? 'date' : 'datetime-local'} value={form.start_time} onChange={e => set('start_time', e.target.value)} required />
          </div>
          <div className="form-group">
            <label className="form-label">{editor?.all_day ? 'Конец (не включая этот день) *' : 'Конец *'}</label>
            <input className="form-input" type={editor?.all_day ? 'date' : 'datetime-local'} value={form.end_time} onChange={e => set('end_time', e.target.value)} required />
          </div>
          <div className="form-group">
            <label className="form-label">Место</label>
            <input className="form-input" value={form.location} onChange={e => set('location', e.target.value)} placeholder="Зал 2" />
          </div>
          <div className="form-group">
            <label className="form-label">Описание</label>
            <textarea className="form-input" value={form.description} onChange={e => set('description', e.target.value)} rows={2} style={{ resize: 'none' }} />
          </div>

          <div className="modal-actions">
            <button type="submit" className="btn btn-primary" disabled={saving || reading || (isEdit && !editor)}>
              {saving ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Создать'}
            </button>
            <button type="button" className="btn btn-secondary" onClick={onClose}>Отмена</button>
          </div>

          {isEdit && scope === 'single' && (
            <button
              type="button"
              className="btn btn-danger"
              style={{ width: '100%', marginTop: 10 }}
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? 'Удаление...' : '🗑 Удалить событие'}
            </button>
          )}
          </fieldset>
        </form>
      </div>
    </div>
  );
}

export default function CalendarView({ userId, isAdmin, active = true, dataVersion = 0, initialPlanningMonth = '' }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null); // null | 'new' | event object
  const [filter, setFilter] = useState('rehearsals');
  const [detailFilter, setDetailFilter] = useState('');
  const [planning, setPlanning] = useState(!!initialPlanningMonth);
  const [calendarUrl, setCalendarUrl] = useState(null);
  const [pollSummary, setPollSummary] = useState({});
  const [now, setNow] = useState(Date.now);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, [active]);

  useEffect(() => {
    client.get('/api/calendar/meta')
      .then(({ data }) => setCalendarUrl(data.calendar_url || null))
      .catch(() => {});
  }, []);

  const fetchEvents = useCallback(async () => {
    try {
      setLoading(true);
      const res = await calendarApi.getEvents(60, true);
      setEvents(res.data.events || []);
      setError(null);
    } catch {
      setError('Не удалось загрузить события');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchPollSummary = useCallback(() => {
    client.get('/api/polls/events-summary')
      .then(r => setPollSummary(r.data.summary || {}))
      .catch(() => setError('Не удалось обновить результаты опросов'));
  }, []);

  useEffect(() => {
    if (active) { fetchEvents(); fetchPollSummary(); }
  }, [active, dataVersion, fetchEvents, fetchPollSummary]);

  const handleSaved = result => {
    setModal(null);
    setNotice(result?.warning || 'Изменения сохранены в Google Calendar');
    fetchEvents();
  };
  const handleDeleted = () => { setModal(null); fetchEvents(); };

  const handleSlotClick = (dt) => {
    if (!isAdmin) return;
    const pad = n => String(n).padStart(2, '0');
    const fmtDt = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
    const end = new Date(dt.getTime() + 2 * 3600000);
    setModal({ start_time: fmtDt(dt), end_time: fmtDt(end) });
  };

  // History remains in WeekCalendar; the list shows ongoing/upcoming events.
  const upcomingEvents = events
    .filter(e => new Date(e.end_time).getTime() > now)
    .sort((a, b) => new Date(a.start_time) - new Date(b.start_time));
  const filters = calendarFilters(upcomingEvents);
  const effectiveFilter = filters.some(f => f.key === filter) ? filter : 'all';
  const filteredEvents = upcomingEvents.filter(e => matchesCalendarFilter(e, effectiveFilter));
  const details = effectiveFilter === 'all' ? [] : calendarDetails(filteredEvents);
  const effectiveDetail = details.length > 1 && details.some(item => item.key === detailFilter) ? detailFilter : '';
  const visibleEvents = filteredEvents.filter(e => !effectiveDetail || getEventDetailKey(e) === effectiveDetail);
  // Once a filter disappears, do not silently revive it after a refresh.
  useEffect(() => {
    if (loading) return;
    if (filter !== effectiveFilter) setFilter(effectiveFilter);
    if (detailFilter !== effectiveDetail) setDetailFilter(effectiveDetail);
  }, [loading, filter, effectiveFilter, detailFilter, effectiveDetail]);

  if (planning) return <PlanningView onClose={() => setPlanning(false)} dataVersion={dataVersion} initialMonth={initialPlanningMonth} isAdmin={isAdmin} />;

  if (loading && events.length === 0) return <div className="empty-state">Загрузка...</div>;

  return (
    <>
      <div className="page-header">
        <div className="page-title">Расписание</div>
        <div style={{ display: 'flex', gap: 8 }}>
          {calendarUrl && (
            <a
              href={calendarUrl}
              target="_blank"
              rel="noreferrer"
              className="btn btn-secondary"
              style={{ fontSize: 13, padding: '6px 10px', textDecoration: 'none' }}
            >
              📅 Google
            </a>
          )}
          {isAdmin && <button className="btn btn-primary" onClick={() => setModal('new')}>+ Добавить</button>}
        </div>
      </div>

      <button className="btn btn-secondary" style={{ width: '100%', marginBottom: 14 }} onClick={() => setPlanning(true)}>Планирование составов →</button>

      <WeekCalendar
        events={events}
        now={now}
        onEventClick={isAdmin ? (e) => setModal(e) : null}
        onSlotClick={handleSlotClick}
      />

      <div className="calendar-filters" role="group" aria-label="Тип событий">
        {filters.map(f => (
          <button
            key={f.key}
            onClick={() => { setFilter(f.key); setDetailFilter(''); }}
            className="calendar-filter"
            aria-pressed={effectiveFilter === f.key}
          >
            {f.label}
          </button>
        ))}
      </div>
      {details.length > 1 && <label className="calendar-detail-filter">
        {effectiveFilter === 'shows' || effectiveFilter === 'rehearsals' ? 'Спектакль / название' : 'Название'}
        <select className="select-input" aria-label="Уточнить события" value={effectiveDetail}
          onChange={e => setDetailFilter(e.target.value)}>
          <option value="">Все названия · {filteredEvents.length}</option>
          {details.map(item => <option key={item.key} value={item.key}>{item.label} · {item.count}</option>)}
        </select>
      </label>}
      <p className="calendar-list-caption">Текущие и ближайшие 60 дней · Событий: {visibleEvents.length}</p>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div role="status" className="alert">{notice}</div>}

      {visibleEvents.length === 0 ? (
        <div className="empty-state">Нет событий</div>
      ) : (
        visibleEvents.map(e => {
          const isPast = new Date(e.end_time).getTime() <= now;
          return (
            <EventCard
              key={e.id}
              event={e}
              userId={userId}
              onEdit={setModal}
              isAdmin={isAdmin}
              isPollable={e.event_type === 'rehearsal' && !isPast}
              isPast={isPast}
              poll={pollSummary[String(e.id)]}
              onPollAction={() => { fetchPollSummary(); fetchEvents(); }}
            />
          );
        })
      )}

      {modal && (
        <EventModal
          event={modal === 'new' ? null : modal}
          onClose={() => setModal(null)}
          onSaved={handleSaved}
          onDeleted={handleDeleted}
        />
      )}
    </>
  );
}
