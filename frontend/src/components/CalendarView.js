import React, { useState, useEffect } from 'react';
import client from '../api/client';

function CalendarView({ userId }) {
  const [events, setEvents] = useState([]);
  const [nextEvent, setNextEvent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchEvents();
  }, []);

  const fetchEvents = async () => {
    try {
      setLoading(true);
      const [eventsRes, nextRes] = await Promise.all([
        client.get('/api/calendar/events'),
        client.get('/api/calendar/events/next'),
      ]);

      setEvents(eventsRes.data.events || []);
      setNextEvent(nextRes.data.event);
    } catch (err) {
      console.error('Failed to fetch events:', err);
      setError('Ошибка при загрузке событий');
    } finally {
      setLoading(false);
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

  if (loading) {
    return <div className="text-center mt-12">⏳ Загрузка...</div>;
  }

  if (error) {
    return (
      <div className="card">
        <div className="text-center" style={{ color: '#dc3545' }}>
          {error}
        </div>
        <button
          className="btn btn-primary"
          onClick={fetchEvents}
          style={{ width: '100%', marginTop: '12px' }}
        >
          Повторить
        </button>
      </div>
    );
  }

  return (
    <div>
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
          ))
        )}
      </div>
    </div>
  );
}

export default CalendarView;
