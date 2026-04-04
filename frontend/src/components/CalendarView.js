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
  { key: 'all',      label: 'Все' },
  { key: 'труппа 1', label: 'Труппа 1' },
  { key: 'труппа 2', label: 'Труппа 2' },
  { key: 'лаба',     label: 'Лаба' },
];

const MONTHS_FULL = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const DOW = ['пн','вт','ср','чт','пт','сб','вс'];

function WeekStrip({ events }) {
  const [weekOffset, setWeekOffset] = useState(0);

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

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const eventsByDay = {};
  events.forEach(e => {
    const key = new Date(e.start_time).toDateString();
    if (!eventsByDay[key]) eventsByDay[key] = [];
    eventsByDay[key].push(e);
  });

  const monthLabel = (() => {
    const first = MONTHS_FULL[days[0].getMonth()];
    const last  = MONTHS_FULL[days[6].getMonth()];
    const year  = days[6].getFullYear();
    return first === last ? `${first} ${year}` : `${first} — ${last} ${year}`;
  })();

  return (
    <div className="card-white" style={{ padding: '10px 12px', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <button onClick={() => setWeekOffset(o => o - 1)} style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#555', padding: '0 4px' }}>‹</button>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#333' }}>{monthLabel}</span>
        <button onClick={() => setWeekOffset(o => o + 1)} style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#555', padding: '0 4px' }}>›</button>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-around' }}>
        {days.map((d, i) => {
          const isToday = d.getTime() === today.getTime();
          const dayEvents = eventsByDay[d.toDateString()] || [];
          return (
            <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3, minWidth: 0, flex: 1 }}>
              <span style={{ fontSize: 10, color: '#aaa' }}>{DOW[i]}</span>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                background: isToday ? '#111' : 'transparent',
                color: isToday ? '#fff' : '#222',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 13, fontWeight: isToday ? 700 : 400,
              }}>
                {d.getDate()}
              </div>
              <div style={{ display: 'flex', gap: 2, height: 8, alignItems: 'center' }}>
                {dayEvents.slice(0, 3).map((_, j) => (
                  <div key={j} style={{ width: 5, height: 5, borderRadius: '50%', background: '#111' }} />
                ))}
                {dayEvents.length > 3 && <span style={{ fontSize: 8, color: '#999', lineHeight: 1 }}>+</span>}
              </div>
            </div>
          );
        })}
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
              padding: '4px 12px',
              borderRadius: 16,
              border: '1px solid #ccc',
              background: filter === f.key ? '#111' : '#fff',
              color: filter === f.key ? '#fff' : '#111',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      <WeekStrip events={visibleEvents} />

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
