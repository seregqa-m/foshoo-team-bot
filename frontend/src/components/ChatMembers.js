import React, { useEffect, useState } from 'react';
import client from '../api/client';

const statuses = { member: 'В группе', left: 'Вышел из группы', pending: 'Проверяем членство', disconnected: 'Группа отключена' };

export default function ChatMembers({ chatId }) {
  const [members, setMembers] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [reload, setReload] = useState(0);
  const endpoint = `/api/admin/theater/chats/${chatId}/members`;
  useEffect(() => {
    let active = true;
    setBusy(true); setError('');
    client.get(endpoint).then(({ data }) => { if (active) setMembers(data.members); })
      .catch(() => { if (active) setError('Не удалось загрузить участников.'); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [endpoint, reload]);
  return <div>
    <p>Список пополняется после голосования и событий вступления в группу. Полный список старых участников Telegram боту не передаёт.</p>
    <p>Все зарегистрированные участники, которые состоят в группе, учитываются в занятости. Напоминания получают те, кто ещё не ответил.</p>
    {error && <p role="alert">{error}</p>}
    <button className="btn btn-secondary" disabled={busy} onClick={() => setReload(value => value + 1)}>Обновить участников</button>
    {busy && <p role="status">Загрузка…</p>}
    {!busy && !members.length && <p>Участники пока не зарегистрированы.</p>}
    {members.map(person => <div key={person.user_id} className="theater-panel__note">
      <strong>{person.name}</strong>{person.username && ` (@${person.username})`} · {statuses[person.status] || person.status}
    </div>)}
  </div>;
}
