import React, { useState, useEffect } from 'react';
import { Calendar, dateFnsLocalizer } from 'react-big-calendar';
import { format, parse, startOfWeek, getDay } from 'date-fns';
import ru from 'date-fns/locale/ru';
import 'react-big-calendar/lib/css/react-big-calendar.css';
import * as calendarApi from '../api/calendar';

const locales = { ru };
const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek: (date) => startOfWeek(date, { weekStartsOn: 1 }),
  getDay,
  locales,
});

function CalendarView({ userId }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [launchingPoll, setLaunchingPoll] = useState(false);
  const [pollSuccess, setPollSuccess] = useState(false);
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
      const res = await calendarApi.getEvents(90);
      setEvents(res.data.events || []);
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
    setFormData({ title: '', start_time: '', end_time: '', location: '', description: '' });
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
    if (!window.confirm('Вы уверены, что хотите удалить это событие?')) return;
    try {
      await calendarApi.deleteEvent(eventId);
      setSelectedEvent(null);
      await fetchEvents();
      setError(null);
    } catch (err) {
      console.error('Failed to delete event:', err);
      setError('Ошибка при удалении события');
    }
  };

  const handleLaunchPoll = async (eventId) => {
    if (!userId) {
      setError('Требуется авторизация через Telegram');
      return;
    }
    try {
      setLaunchingPoll(true);
      setPollSuccess(false);
      await calendarApi.launchPoll(eventId, userId);
      setPollSuccess(true);
      setError(null);
    } catch (err) {
      console.error('Failed to launch poll:', err);
      setError(err.response?.data?.detail || 'Ошибка при запуске опроса');
    } finally {
      setLaunchingPoll(false);
    }
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleString('ru-RU', {
      weekday: 'short', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  };

  const calendarEvents = events.map((e) => ({
    ...e,
    start: new Date(e.start_time),
    end: new Date(e.end_time),
  }));

  if (loading) {
    return <div className="text-center mt-12">⏳ Загрузка...</div>;
  }

  return (
    <div>
      {error && (
        <div className="card" style={{ backgroundColor: '#f8d7da', borderColor: '#dc3545', marginBottom: '8px' }}>
          <div style={{ color: '#721c24' }}>{error}</div>
        </div>
      )}

      {/* Toolbar */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', padding: '0 8px' }}>
        <button className="btn btn-primary" onClick={handleAddClick} style={{ flex: 1 }}>
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

      {/* Weekly calendar */}
      <div style={{ padding: '0 4px' }}>
        <Calendar
          localizer={localizer}
          events={calendarEvents}
          defaultView="week"
          views={['week', 'day']}
          defaultDate={new Date()}
          style={{ height: 520 }}
          culture="ru"
          onSelectEvent={(event) => {
            setSelectedEvent(event);
            setPollSuccess(false);
          }}
          messages={{
            week: 'Неделя',
            day: 'День',
            today: 'Сегодня',
            previous: '←',
            next: '→',
            noEventsInRange: 'Нет событий',
          }}
        />
      </div>

      {/* Event detail popup */}
      {selectedEvent && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => { setSelectedEvent(null); setPollSuccess(false); }}
        >
          <div
            className="card"
            style={{ width: '90%', maxWidth: '400px' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontWeight: 'bold', fontSize: '16px', marginBottom: '6px' }}>
              {selectedEvent.title}
            </div>
            <div style={{ fontSize: '13px', color: '#666', marginBottom: '4px' }}>
              {formatDate(selectedEvent.start_time)}
            </div>
            {selectedEvent.location && (
              <div style={{ fontSize: '12px', color: '#999', marginBottom: '8px' }}>
                📍 {selectedEvent.location}
              </div>
            )}
            {selectedEvent.description && (
              <div style={{ fontSize: '12px', marginBottom: '12px' }}>
                {selectedEvent.description}
              </div>
            )}

            {pollSuccess && (
              <div style={{ color: '#28a745', fontSize: '13px', marginBottom: '10px' }}>
                ✅ Опрос отправлен в группу
              </div>
            )}

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button
                className="btn btn-primary"
                style={{ flex: 1 }}
                onClick={() => { handleEditClick(selectedEvent); setSelectedEvent(null); }}
              >
                ✏️ Изменить
              </button>
              <button
                className="btn btn-danger"
                style={{ flex: 1 }}
                onClick={() => handleDelete(selectedEvent.id)}
              >
                🗑️ Удалить
              </button>
              <button
                className="btn btn-secondary"
                style={{ flex: '0 0 100%' }}
                disabled={launchingPoll || pollSuccess}
                onClick={() => handleLaunchPoll(selectedEvent.id)}
              >
                {launchingPoll ? '⌛ Отправка...' : pollSuccess ? '✅ Отправлен' : '🗳️ Запустить опрос'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create/Edit form modal */}
      {showForm && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setShowForm(false)}
        >
          <div
            className="card"
            style={{ width: '90%', maxWidth: '500px', maxHeight: '80vh', overflow: 'auto' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontWeight: 'bold', fontSize: '16px', marginBottom: '12px' }}>
              {editingId ? '✏️ Редактировать событие' : '➕ Новое событие'}
            </div>

            <form onSubmit={handleFormSubmit}>
              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>Название*</label>
                <input
                  type="text"
                  name="title"
                  value={formData.title}
                  onChange={handleFormChange}
                  placeholder="Название события"
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc', marginTop: '4px', fontSize: '14px' }}
                  required
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>Начало*</label>
                <input
                  type="datetime-local"
                  name="start_time"
                  value={formData.start_time.slice(0, 16)}
                  onChange={(e) => setFormData((prev) => ({ ...prev, start_time: e.target.value + ':00' }))}
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc', marginTop: '4px', fontSize: '14px' }}
                  required
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>Конец*</label>
                <input
                  type="datetime-local"
                  name="end_time"
                  value={formData.end_time.slice(0, 16)}
                  onChange={(e) => setFormData((prev) => ({ ...prev, end_time: e.target.value + ':00' }))}
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc', marginTop: '4px', fontSize: '14px' }}
                  required
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>Место</label>
                <input
                  type="text"
                  name="location"
                  value={formData.location}
                  onChange={handleFormChange}
                  placeholder="Место проведения"
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc', marginTop: '4px', fontSize: '14px' }}
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ fontSize: '12px', color: '#666' }}>Описание</label>
                <textarea
                  name="description"
                  value={formData.description}
                  onChange={handleFormChange}
                  placeholder="Описание события"
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc', marginTop: '4px', fontSize: '14px', resize: 'vertical' }}
                  rows="3"
                />
              </div>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="submit" className="btn btn-primary" style={{ flex: 1 }}>
                  {editingId ? '💾 Сохранить' : '✅ Создать'}
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => setShowForm(false)} style={{ flex: 1 }}>
                  ✕ Отмена
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default CalendarView;
