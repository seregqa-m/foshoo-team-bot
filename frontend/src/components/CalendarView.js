import React, { useState, useEffect } from 'react';
import * as calendarApi from '../api/calendar';

function CalendarView({ userId }) {
  const [events, setEvents] = useState([]);
  const [nextEvent, setNextEvent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formData, setFormData] = useState({
    title: '',
    start_time: '',
    end_time: '',
    location: '',
    description: '',
  });

  useEffect(() => {
    fetchEvents();
  }, []);

  const fetchEvents = async () => {
    try {
      setLoading(true);
      const [eventsRes, nextRes] = await Promise.all([
        calendarApi.getEvents(),
        calendarApi.getNextEvent(),
      ]);

      setEvents(eventsRes.data.events || []);
      setNextEvent(nextRes.data.event);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch events:', err);
      setError('Ошибка при загрузке событий');
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    try {
      setSyncing(true);
      await calendarApi.syncCalendar();
      await fetchEvents();
      setError(null);
    } catch (err) {
      console.error('Sync failed:', err);
      setError('Ошибка при синхронизации');
    } finally {
      setSyncing(false);
    }
  };

  const handleAddClick = () => {
    setEditingId(null);
    setFormData({
      title: '',
      start_time: '',
      end_time: '',
      location: '',
      description: '',
    });
    setShowForm(true);
  };

  const handleEditClick = (event) => {
    setEditingId(event.id);
    setFormData({
      title: event.title,
      start_time: event.start_time,
      end_time: event.end_time,
      location: event.location || '',
      description: event.description || '',
    });
    setShowForm(true);
  };

  const handleFormChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleFormSubmit = async (e) => {
    e.preventDefault();
    try {
      if (!formData.title || !formData.start_time || !formData.end_time) {
        setError('Заполните обязательные поля');
        return;
      }

      if (editingId) {
        await calendarApi.updateEvent(editingId, formData);
      } else {
        await calendarApi.createEvent(formData);
      }

      setShowForm(false);
      await fetchEvents();
      setError(null);
    } catch (err) {
      console.error('Failed to save event:', err);
      setError('Ошибка при сохранении события');
    }
  };

  const handleDelete = async (eventId) => {
    if (!window.confirm('Вы уверены, что хотите удалить это событие?')) {
      return;
    }

    try {
      await calendarApi.deleteEvent(eventId);
      await fetchEvents();
      setError(null);
    } catch (err) {
      console.error('Failed to delete event:', err);
      setError('Ошибка при удалении события');
    }
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleString('ru-RU', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getGoogleCalendarLink = (event) => {
    if (event.google_event_id) {
      return `https://calendar.google.com/calendar/u/0/r/eventedit/${event.google_event_id}`;
    }
    return null;
  };

  if (loading) {
    return <div className="text-center mt-12">⏳ Загрузка...</div>;
  }

  return (
    <div>
      {error && (
        <div className="card" style={{ backgroundColor: '#f8d7da', borderColor: '#dc3545' }}>
          <div style={{ color: '#721c24' }}>{error}</div>
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', padding: '0 8px' }}>
        <button
          className="btn btn-primary"
          onClick={handleAddClick}
          style={{ flex: 1 }}
        >
          ➕ Добавить
        </button>
        <button
          className="btn btn-secondary"
          onClick={handleSync}
          disabled={syncing}
          style={{ flex: 1, opacity: syncing ? 0.5 : 1 }}
        >
          {syncing ? '⌛ Синхр...' : '🔄 Синхр'}
        </button>
      </div>

      {showForm && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setShowForm(false)}
        >
          <div
            className="card"
            style={{
              width: '90%',
              maxWidth: '500px',
              maxHeight: '80vh',
              overflow: 'auto',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontWeight: 'bold', fontSize: '16px', marginBottom: '12px' }}>
              {editingId ? '✏️ Редактировать событие' : '➕ Новое событие'}
            </div>

            <form onSubmit={handleFormSubmit}>
              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>
                  Название*
                </label>
                <input
                  type="text"
                  name="title"
                  value={formData.title}
                  onChange={handleFormChange}
                  placeholder="Название события"
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid #ccc',
                    marginTop: '4px',
                    fontSize: '14px',
                  }}
                  required
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>
                  Начало*
                </label>
                <input
                  type="datetime-local"
                  name="start_time"
                  value={formData.start_time.slice(0, 16)}
                  onChange={(e) =>
                    setFormData((prev) => ({
                      ...prev,
                      start_time: e.target.value + ':00',
                    }))
                  }
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid #ccc',
                    marginTop: '4px',
                    fontSize: '14px',
                  }}
                  required
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>
                  Конец*
                </label>
                <input
                  type="datetime-local"
                  name="end_time"
                  value={formData.end_time.slice(0, 16)}
                  onChange={(e) =>
                    setFormData((prev) => ({
                      ...prev,
                      end_time: e.target.value + ':00',
                    }))
                  }
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid #ccc',
                    marginTop: '4px',
                    fontSize: '14px',
                  }}
                  required
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>
                  Место
                </label>
                <input
                  type="text"
                  name="location"
                  value={formData.location}
                  onChange={handleFormChange}
                  placeholder="Место проведения"
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid #ccc',
                    marginTop: '4px',
                    fontSize: '14px',
                  }}
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>
                  Описание
                </label>
                <textarea
                  name="description"
                  value={formData.description}
                  onChange={handleFormChange}
                  placeholder="Описание события"
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid #ccc',
                    marginTop: '4px',
                    fontSize: '14px',
                    resize: 'vertical',
                  }}
                  rows="3"
                />
              </div>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  type="submit"
                  className="btn btn-primary"
                  style={{ flex: 1 }}
                >
                  {editingId ? '💾 Сохранить' : '✅ Создать'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowForm(false)}
                  style={{ flex: 1 }}
                >
                  ✕ Отмена
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {nextEvent && (
        <div className="card" style={{ borderLeft: '4px solid #0088cc' }}>
          <div style={{ fontWeight: 'bold', fontSize: '14px' }}>
            📌 Следующее занятие
          </div>
          <div style={{ fontSize: '16px', fontWeight: 'bold', marginTop: '8px' }}>
            {nextEvent.title}
          </div>
          <div style={{ fontSize: '14px', color: '#666', marginTop: '4px' }}>
            {formatDate(nextEvent.start_time)}
          </div>
          {nextEvent.location && (
            <div style={{ fontSize: '12px', color: '#999', marginTop: '4px' }}>
              📍 {nextEvent.location}
            </div>
          )}
          {nextEvent.description && (
            <div style={{ fontSize: '12px', color: '#666', marginTop: '8px' }}>
              {nextEvent.description}
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '14px', marginBottom: '8px' }}>
          📅 Расписание
        </div>

        {events.length === 0 ? (
          <div className="text-center text-secondary mt-12">
            Нет предстоящих событий
          </div>
        ) : (
          events.map((event) => (
            <div key={event.id} className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 'bold', fontSize: '14px' }}>
                    {event.title}
                  </div>
                  <div style={{ fontSize: '12px', color: '#666', marginTop: '4px' }}>
                    {formatDate(event.start_time)}
                  </div>
                  {event.location && (
                    <div style={{ fontSize: '12px', color: '#999', marginTop: '4px' }}>
                      📍 {event.location}
                    </div>
                  )}
                  {event.description && (
                    <div style={{ fontSize: '12px', marginTop: '8px' }}>
                      {event.description}
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: '4px', marginLeft: '8px' }}>
                  <button
                    onClick={() => handleEditClick(event)}
                    style={{
                      backgroundColor: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: '16px',
                    }}
                  >
                    ✏️
                  </button>
                  <button
                    onClick={() => handleDelete(event.id)}
                    style={{
                      backgroundColor: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: '16px',
                    }}
                  >
                    🗑️
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default CalendarView;
