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

function EventCard({ event, userId, onEdit, onPollSent }) {
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
          <button className="btn btn-secondary" onClick={() => onEdit(event)}>✏️ Ред.</button>
          <button
            className={`btn ${pollDone ? 'btn-success' : 'btn-secondary'}`}
            onClick={handlePoll}
            disabled={polling || pollDone}
          >
            {polling ? '⌛' : pollDone ? '✅ Отправлен' : '🗳️ Опрос'}
          </button>
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

export default function CalendarView({ userId }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null); // null | 'new' | event object
  const [filter, setFilter] = useState('труппа 1');

  const fetchEvents = async () => {
    try {
      setLoading(true);
      const res = await calendarApi.getEvents(90);
      setEvents(res.data.events || []);
      setError(null);
    } catch {
      setError('Не удалось загрузить события');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchEvents(); }, []);

  const handleSaved = () => { setModal(null); fetchEvents(); };
  const handleDeleted = () => { setModal(null); fetchEvents(); };

  const visibleEvents = filter === 'all'
    ? events
    : events.filter(e => e.title.toLowerCase().includes(filter));

  if (loading) return <div className="empty-state">Загрузка...</div>;

  return (
    <>
      <div className="page-header">
        <div className="page-title">Расписание</div>
        <button className="btn btn-primary" onClick={() => setModal('new')}>+ Добавить</button>
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

      {error && <div className="alert alert-error">{error}</div>}

      {visibleEvents.length === 0 ? (
        <div className="empty-state">Нет предстоящих событий</div>
      ) : (
        visibleEvents.map(e => (
          <EventCard
            key={e.id}
            event={e}
            userId={userId}
            onEdit={setModal}
            onPollSent={fetchEvents}
          />
        ))
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
