import React, { useState, useEffect } from 'react';
import * as calendarApi from '../api/calendar';

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

const FILTERS = [
  { key: 'all',      label: 'Все',       color: '#E5E7EB' },
  { key: 'труппа 1', label: 'Труппа 1',  color: '#C4B5FD' },
  { key: 'труппа 2', label: 'Труппа 2',  color: '#FDE68A' },
  { key: 'лаба',     label: 'Лаба',      color: '#FCA5A5' },
];

const MONTHS_FULL = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const DOW = ['пн','вт','ср','чт','пт','сб','вс'];

const HOUR_START = 9;
const HOUR_END   = 24;
const HOUR_H     = 18;
const HEADER_H   = 42;
const LABEL_W    = 28;

function getEventColor(title, showNames) {
  const t = title.toLowerCase();
  if (t.includes('труппа 1') || showNames.some(s => t.includes(s))) return '#C4B5FD';
  if (t.includes('труппа 2')) return '#FDE68A';
  if (t.includes('лаба')) return '#FCA5A5';
  return '#D1D5DB';
}

function WeekCalendar({ events, showNames }) {
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

  const timeToY = dt => {
    const h = Math.max(HOUR_START, Math.min(HOUR_END, dt.getHours() + dt.getMinutes() / 60));
    return HEADER_H + (h - HOUR_START) * HOUR_H;
  };

  const monthLabel = (() => {
    const f = MONTHS_FULL[days[0].getMonth()], l = MONTHS_FULL[days[6].getMonth()], y = days[6].getFullYear();
    return f === l ? `${f} ${y}` : `${f} — ${l} ${y}`;
  })();

  const fmt = dt => `${String(dt.getHours()).padStart(2,'0')}:${String(dt.getMinutes()).padStart(2,'0')}`;

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
          <svg width={totalW} height={svgH} style={{ display: 'block' }}>
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
              const y2 = timeToY(endDt);
              const h  = Math.max(6, y2 - y1);
              const x  = LABEL_W + dayIdx * colW + 3;
              const w  = colW - 6;
              const color = getEventColor(e.title, showNames);
              return (
                <rect key={idx} x={x} y={y1} width={w} height={h} rx={3}
                  fill={color} fillOpacity={0.9} style={{ cursor: 'pointer' }}
                  onMouseEnter={() => setTooltip({ title: e.title, time: `${fmt(startDt)}–${fmt(endDt)}`, x: x + w/2, y: y1 })}
                  onMouseLeave={() => setTooltip(null)}
                  onTouchStart={() => setTooltip({ title: e.title, time: `${fmt(startDt)}–${fmt(endDt)}`, x: x + w/2, y: y1 })}
                  onTouchEnd={() => setTimeout(() => setTooltip(null), 2000)}
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

function EventCard({ event, userId, onEdit, onPollSent, isAdmin, isPollable }) {
  const start = new Date(event.start_time);
  const [polling, setPolling] = useState(false);
  const [pollDone, setPollDone] = useState(false);
  const [pollError, setPollError] = useState(null);

  const handlePoll = async () => {
    if (!userId) { setPollError('Нет userId'); return; }
    try {
      setPolling(true);
      setPollError(null);
      await calendarApi.launchPoll(event.id, userId);
      setPollDone(true);
      onPollSent && onPollSent();
    } catch (e) {
      setPollError(e.response?.data?.detail || 'Ошибка');
    } finally {
      setPolling(false);
    }
  };

  return (
    <div className="event-card">
      <div className="event-date-block">
        <div className="event-date-day">{start.getDate()}</div>
        <div className="event-date-month">{MONTHS[start.getMonth()]}</div>
        <div className="event-date-dow">{DAYS[start.getDay()]}</div>
      </div>
      <div className="event-body">
        <div className="event-title">{event.title}</div>
        <div className="event-meta">
          {formatTime(event.start_time)} – {formatTime(event.end_time)}
          {event.location ? `  📍 ${event.location}` : ''}
        </div>
        {pollError && <div style={{ fontSize: 12, color: 'var(--danger)', marginBottom: 8 }}>{pollError}</div>}
        <div className="event-actions">
          {isAdmin && <button className="btn btn-secondary" onClick={() => onEdit(event)}>✏️ Ред.</button>}
          {isPollable && (
            <button
              className={`btn ${pollDone ? 'btn-success' : 'btn-secondary'}`}
              onClick={handlePoll}
              disabled={polling || pollDone}
            >
              {polling ? '⌛' : pollDone ? '✅ Отправлен' : '🗳️ Опрос'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function EventModal({ event, onClose, onSaved, onDeleted }) {
  const isEdit = !!event?.id;
  const [form, setForm] = useState(
    isEdit
      ? { ...event, start_time: toLocalInput(event.start_time), end_time: toLocalInput(event.end_time) }
      : { ...EMPTY_FORM }
  );
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const handleSave = async (e) => {
    e.preventDefault();
    if (!form.title || !form.start_time || !form.end_time) {
      setError('Заполните обязательные поля');
      return;
    }
    try {
      setSaving(true);
      setError(null);
      const data = { ...form, start_time: form.start_time + ':00', end_time: form.end_time + ':00' };
      if (isEdit) {
        await calendarApi.updateEvent(event.id, data);
      } else {
        await calendarApi.createEvent(data);
      }
      onSaved();
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка при сохранении');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Удалить событие?')) return;
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

        {error && <div className="alert alert-error">{error}</div>}

        <form onSubmit={handleSave}>
          <div className="form-group">
            <label className="form-label">Название *</label>
            <input className="form-input" value={form.title} onChange={e => set('title', e.target.value)} placeholder="Репетиция «Гамлет»" required />
          </div>
          <div className="form-group">
            <label className="form-label">Начало *</label>
            <input className="form-input" type="datetime-local" value={form.start_time} onChange={e => set('start_time', e.target.value)} required />
          </div>
          <div className="form-group">
            <label className="form-label">Конец *</label>
            <input className="form-input" type="datetime-local" value={form.end_time} onChange={e => set('end_time', e.target.value)} required />
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
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Создать'}
            </button>
            <button type="button" className="btn btn-secondary" onClick={onClose}>Отмена</button>
          </div>

          {isEdit && (
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
        </form>
      </div>
    </div>
  );
}

export default function CalendarView({ userId, isAdmin }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null); // null | 'new' | event object
  const [filter, setFilter] = useState('труппа 1');
  const [showNames, setShowNames] = useState([]);

  useEffect(() => {
    fetch(`${process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000'}/api/sheets/shows`)
      .then(r => r.json())
      .then(data => setShowNames((data.shows || []).map(s => s.toLowerCase())))
      .catch(() => {});
  }, []);

  const fetchEvents = async (currentFilter) => {
    const days = currentFilter === 'all' ? 30 : 60;
    try {
      setLoading(true);
      const res = await calendarApi.getEvents(days);
      setEvents(res.data.events || []);
      setError(null);
    } catch {
      setError('Не удалось загрузить события');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchEvents(filter); }, [filter]);

  const handleSaved = () => { setModal(null); fetchEvents(filter); };
  const handleDeleted = () => { setModal(null); fetchEvents(filter); };

  const visibleEvents = filter === 'all'
    ? events
    : filter === 'труппа 1'
      ? events.filter(e => {
          const t = e.title.toLowerCase();
          return t.includes('труппа 1') || showNames.some(s => t.includes(s));
        })
      : events.filter(e => e.title.toLowerCase().includes(filter));

  if (loading) return <div className="empty-state">Загрузка...</div>;

  return (
    <>
      <div className="page-header">
        <div className="page-title">Расписание</div>
        {isAdmin && <button className="btn btn-primary" onClick={() => setModal('new')}>+ Добавить</button>}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            style={{
              padding: '4px 12px', borderRadius: 16, fontSize: 13, cursor: 'pointer',
              border: filter === f.key ? '2px solid #555' : '1.5px solid transparent',
              background: f.color,
              color: '#333', fontWeight: filter === f.key ? 700 : 400,
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      <WeekCalendar events={visibleEvents} showNames={showNames} />

      {error && <div className="alert alert-error">{error}</div>}

      {visibleEvents.length === 0 ? (
        <div className="empty-state">Нет предстоящих событий</div>
      ) : (
        visibleEvents.map(e => {
          const t = e.title.toLowerCase();
          const isT1 = t.includes('труппа 1') || showNames.some(s => t.includes(s));
          const isPerformance = showNames.some(s => t.includes(s));
          return (
            <EventCard
              key={e.id}
              event={e}
              userId={userId}
              onEdit={setModal}
              onPollSent={fetchEvents}
              isAdmin={isAdmin}
              isPollable={isT1 && !isPerformance}
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
