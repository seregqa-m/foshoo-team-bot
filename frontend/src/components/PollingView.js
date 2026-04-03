import React, { useState, useEffect } from 'react';
import client from '../api/client';

function PollingView() {
  const [polls, setPolls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchPolls();
  }, []);

  const fetchPolls = async () => {
    try {
      setLoading(true);
      const response = await client.get('/api/polls/all');
      setPolls(response.data.polls || []);
    } catch (err) {
      console.error('Failed to fetch polls:', err);
      setError('Ошибка при загрузке опросов');
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (isoString) => {
    const d = new Date(isoString);
    return d.toLocaleString('ru-RU', {
      day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    });
  };

  if (loading) return <div className="text-center mt-12">⏳ Загрузка опросов...</div>;

  return (
    <div>
      {error && (
        <div className="card" style={{ backgroundColor: '#fff3cd', borderColor: '#ffc107' }}>
          <div style={{ color: '#856404' }}>{error}</div>
        </div>
      )}

      {polls.length === 0 ? (
        <div className="text-center text-secondary mt-12">
          Нет опросов. Запустите опрос из карточки события в Календаре.
        </div>
      ) : (
        polls.map((poll) => (
          <div key={poll.id} className="card">
            {poll.calendar_event && (
              <div style={{ fontSize: '11px', color: '#999', marginBottom: '4px' }}>
                📅 {poll.calendar_event.title} · {formatDate(poll.calendar_event.start_time)}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <div style={{ fontWeight: 'bold', fontSize: '14px', flex: 1, marginRight: '8px' }}>
                {poll.title}
              </div>
              <span style={{
                fontSize: '11px',
                padding: '2px 8px',
                borderRadius: '10px',
                backgroundColor: poll.is_active ? '#d4edda' : '#f0f0f0',
                color: poll.is_active ? '#155724' : '#666',
                whiteSpace: 'nowrap',
              }}>
                {poll.is_active ? 'Активен' : 'Закрыт'}
              </span>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <div style={{ flex: 1, textAlign: 'center', padding: '8px 4px', backgroundColor: '#d4edda', borderRadius: '8px' }}>
                <div style={{ fontSize: '20px', fontWeight: 'bold', color: '#155724' }}>{poll.votes.yes}</div>
                <div style={{ fontSize: '11px', color: '#155724' }}>Буду ✅</div>
              </div>
              <div style={{ flex: 1, textAlign: 'center', padding: '8px 4px', backgroundColor: '#f8d7da', borderRadius: '8px' }}>
                <div style={{ fontSize: '20px', fontWeight: 'bold', color: '#721c24' }}>{poll.votes.no}</div>
                <div style={{ fontSize: '11px', color: '#721c24' }}>Не буду ❌</div>
              </div>
              <div style={{ flex: 1, textAlign: 'center', padding: '8px 4px', backgroundColor: '#fff3cd', borderRadius: '8px' }}>
                <div style={{ fontSize: '20px', fontWeight: 'bold', color: '#856404' }}>{poll.votes.maybe}</div>
                <div style={{ fontSize: '11px', color: '#856404' }}>Опоздаю ⏰</div>
              </div>
            </div>

            <div style={{ fontSize: '11px', color: '#aaa', marginTop: '8px' }}>
              Всего голосов: {poll.total_votes} · {formatDate(poll.created_at)}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

export default PollingView;
