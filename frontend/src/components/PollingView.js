import React, { useState, useEffect } from 'react';
import client from '../api/client';

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export default function PollingView() {
  const [polls, setPolls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    client.get('/api/polls/all')
      .then(r => setPolls(r.data.polls || []))
      .catch(() => setError('Не удалось загрузить опросы'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="empty-state">Загрузка...</div>;

  return (
    <>
      <div className="page-header">
        <div className="page-title">Опросы</div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {polls.length === 0 ? (
        <div className="empty-state">Нет опросов. Запустите опрос из карточки события.</div>
      ) : (
        polls.map(poll => (
          <div key={poll.id} className="card">
            {poll.calendar_event && (
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                📅 {poll.calendar_event.title} · {formatDate(poll.calendar_event.start_time)}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontWeight: 600, fontSize: 15, flex: 1, marginRight: 8 }}>{poll.title}</div>
              <span style={{
                fontSize: 11,
                padding: '3px 10px',
                borderRadius: 20,
                background: poll.is_active ? '#e6f7ef' : 'var(--border)',
                color: poll.is_active ? 'var(--success)' : 'var(--muted)',
                fontWeight: 600,
              }}>
                {poll.is_active ? 'Активен' : 'Закрыт'}
              </span>
            </div>

            <div className="vote-grid">
              <div className="vote-block vote-block-yes">
                <div className="vote-count vote-count-yes">{poll.votes.yes}</div>
                <div className="vote-label">Буду ✅</div>
              </div>
              <div className="vote-block vote-block-no">
                <div className="vote-count vote-count-no">{poll.votes.no}</div>
                <div className="vote-label">Не буду ❌</div>
              </div>
              <div className="vote-block vote-block-maybe">
                <div className="vote-count vote-count-maybe">{poll.votes.maybe}</div>
                <div className="vote-label">Опоздаю ⏰</div>
              </div>
            </div>

            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 10 }}>
              Всего: {poll.total_votes} · {formatDate(poll.created_at)}
            </div>
          </div>
        ))
      )}
    </>
  );
}
