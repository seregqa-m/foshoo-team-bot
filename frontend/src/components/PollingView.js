import React, { useState, useEffect } from 'react';
import client from '../api/client';

function PollingView({ userId }) {
  const [polls, setPolls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [votedPolls, setVotedPolls] = useState(new Set());

  useEffect(() => {
    fetchPolls();
  }, []);

  const fetchPolls = async () => {
    try {
      setLoading(true);
      const response = await client.get('/api/polls');
      setPolls(response.data.polls || []);
    } catch (err) {
      console.error('Failed to fetch polls:', err);
      setError('Ошибка при загрузке опросов');
    } finally {
      setLoading(false);
    }
  };

  const handleVote = async (pollId, answer) => {
    try {
      if (!userId) {
        setError('Требуется авторизация');
        return;
      }

      await client.post(`/api/polls/${pollId}/vote`, { answer }, {
        params: { user_id: userId },
      });

      setVotedPolls((prev) => new Set([...prev, pollId]));
    } catch (err) {
      console.error('Failed to vote:', err);
      setError('Ошибка при голосовании');
    }
  };

  if (loading) {
    return <div className="text-center mt-12">⏳ Загрузка опросов...</div>;
  }

  return (
    <div>
      {error && (
        <div
          className="card"
          style={{ backgroundColor: '#fff3cd', borderColor: '#ffc107' }}
        >
          <div style={{ color: '#856404' }}>{error}</div>
        </div>
      )}

      {polls.length === 0 ? (
        <div className="text-center text-secondary mt-12">
          Нет активных опросов
        </div>
      ) : (
        polls.map((poll) => (
          <div key={poll.id} className="card">
            <div style={{ fontWeight: 'bold', fontSize: '14px' }}>
              {poll.title}
            </div>
            {poll.description && (
              <div
                style={{
                  fontSize: '12px',
                  color: '#666',
                  marginTop: '4px',
                }}
              >
                {poll.description}
              </div>
            )}
            <div style={{ marginTop: '12px', display: 'flex', gap: '8px' }}>
              <button
                className="btn btn-success"
                onClick={() => handleVote(poll.id, 'yes')}
                disabled={votedPolls.has(poll.id)}
                style={{
                  flex: 1,
                  opacity: votedPolls.has(poll.id) ? 0.5 : 1,
                }}
              >
                ✅ Да
              </button>
              <button
                className="btn btn-danger"
                onClick={() => handleVote(poll.id, 'no')}
                disabled={votedPolls.has(poll.id)}
                style={{
                  flex: 1,
                  opacity: votedPolls.has(poll.id) ? 0.5 : 1,
                }}
              >
                ❌ Нет
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => handleVote(poll.id, 'maybe')}
                disabled={votedPolls.has(poll.id)}
                style={{
                  flex: 1,
                  opacity: votedPolls.has(poll.id) ? 0.5 : 1,
                }}
              >
                ❓ Может
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

export default PollingView;
