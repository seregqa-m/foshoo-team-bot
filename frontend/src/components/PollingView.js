import React, { useState, useEffect } from 'react';
import client from '../api/client';

const btnStyle = {
  background: 'none', border: '1px solid #e0e0e0', borderRadius: 8,
  padding: '3px 8px', fontSize: 12, cursor: 'pointer', color: '#444',
};

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export default function PollingView() {
  const [polls, setPolls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionMsg, setActionMsg] = useState(null);

  const loadPolls = () => {
    client.get('/api/polls/all')
      .then(r => setPolls(r.data.polls || []))
      .catch(() => setError('Не удалось загрузить опросы'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadPolls(); }, []);

  const notify = (msg) => { setActionMsg(msg); setTimeout(() => setActionMsg(null), 3000); };

  const stopPoll = async (id) => {
    try { await client.post(`/api/polls/${id}/stop`); loadPolls(); notify('Опрос остановлен'); }
    catch (e) { notify('Ошибка при остановке'); }
  };

  const pinPoll = async (id) => {
    try { await client.post(`/api/polls/${id}/pin`); notify('Сообщение закреплено'); }
    catch (e) { notify(e.response?.data?.detail || 'Ошибка при закреплении'); }
  };

  const deletePoll = async (id) => {
    if (!window.confirm('Удалить опрос из БД?')) return;
    try {
      await client.delete(`/api/polls/${id}`);
      loadPolls(); notify('Опрос удалён');
    } catch (e) {
      if (e.response?.status === 409) {
        if (window.confirm(e.response.data.detail + '\n\nВсё равно удалить?')) {
          await client.delete(`/api/polls/${id}?force=true`);
          loadPolls(); notify('Опрос удалён');
        }
      } else {
        notify('Ошибка при удалении');
      }
    }
  };

  if (loading) return <div className="empty-state">Загрузка...</div>;

  return (
    <>
      <div className="page-header">
        <div className="page-title">Опросы</div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {actionMsg && <div className="alert alert-success">{actionMsg}</div>}

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

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                Всего: {poll.total_votes} · {formatDate(poll.created_at)}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {poll.telegram_message_id && (
                  <button onClick={() => pinPoll(poll.id)} style={btnStyle}>
                    📌
                  </button>
                )}
                {poll.is_active && (
                  <button onClick={() => stopPoll(poll.id)} style={btnStyle}>
                    Стоп
                  </button>
                )}
                <button onClick={() => deletePoll(poll.id)} style={{ ...btnStyle, color: '#bbb' }}>
                  ✕
                </button>
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}
