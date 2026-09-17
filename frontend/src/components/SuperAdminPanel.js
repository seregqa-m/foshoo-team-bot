import React, { useEffect, useState } from 'react';
import client from '../api/client';

const name = user => user.display_name || (user.username ? `@${user.username}` : `ID ${user.telegram_user_id}`);
const errorText = (error, fallback) => typeof error.response?.data?.detail === 'string' ? error.response.data.detail : fallback;

export default function SuperAdminPanel({ currentUserId }) {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [searching, setSearching] = useState(false);
  const [searchDone, setSearchDone] = useState(false);
  const [error, setError] = useState('');
  const [searchError, setSearchError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    client.get('/api/admin/superadmins')
      .then(({ data: result }) => { if (active) setData(result); })
      .catch(e => { if (active) { setData(null); setError(errorText(e, 'Не удалось загрузить суперадминистраторов')); } });
    return () => { active = false; };
  }, [revision]);

  useEffect(() => {
    let active = true;
    setUsers([]); setSelected(null); setSearchError(''); setSearchDone(false);
    const q = query.trim();
    if (q.length < 2) { setSearching(false); return; }
    setSearching(true);
    const timer = setTimeout(() => {
      client.get('/api/admin/users', { params: { q } })
        .then(({ data: result }) => { if (active) { setUsers(result.users); setSearchDone(true); } })
        .catch(e => { if (active) setSearchError(errorText(e, 'Не удалось найти пользователя')); })
        .finally(() => { if (active) setSearching(false); });
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [query, revision]);

  const change = async (target, grant) => {
    if (busy) return;
    setBusy(true); setError(''); setMessage('');
    try {
      if (grant) await client.post('/api/admin/superadmins', { telegram_user_id: target.telegram_user_id });
      else await client.delete(`/api/admin/superadmins/${target.telegram_user_id}`);
      setSelected(null); setQuery(''); setRevision(n => n + 1);
      setMessage(grant ? `${name(target)} — теперь суперадминистратор.` : `Глобальные права ${name(target)} сняты.`);
    } catch (e) {
      setError(errorText(e, 'Не удалось подтвердить изменение. Обновите список перед повторной попыткой.'));
      setRevision(n => n + 1);
    } finally { setBusy(false); }
  };

  return <section aria-label="Суперадминистраторы">
    <div className="section-label" style={{ marginTop: 20 }}>Управление театром</div>
    <div className="card-white" style={{ padding: 16 }}>
      <h3 style={{ margin: '0 0 8px', fontSize: 16 }}>Суперадминистраторы</h3>
      <p style={{ fontSize: 13, color: '#666', lineHeight: 1.5 }}>Полный доступ к управлению театром. Роль не зависит от админства в Telegram-чате.</p>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {message && <div className="alert alert-success" role="status">{message}</div>}
      {!data ? <button className="btn btn-secondary" onClick={() => { setError(''); setRevision(n => n + 1); }}>Обновить список</button> : <>
        <ul style={{ listStyle: 'none', padding: 0 }}>
          {data.admins.map(user => <li key={user.telegram_user_id} style={{ padding: '10px 0', borderBottom: '1px solid #eee' }}>
            <strong>{name(user)}{user.telegram_user_id === currentUserId ? ' (вы)' : ''}</strong>
            <div style={{ fontSize: 12, color: '#777', margin: '4px 0 8px' }}>{user.username ? `@${user.username} · ` : ''}ID {user.telegram_user_id}</div>
            <button className="btn btn-secondary" disabled={busy || data.admins.length <= 1}
              onClick={() => setSelected({ ...user, revoke: true })}>Снять глобальные права</button>
          </li>)}
        </ul>
        {data.admins.length === 1 && <p style={{ fontSize: 12, color: '#777' }}>Последнего суперадминистратора удалить нельзя.</p>}
        <label style={{ display: 'block', fontSize: 13 }}>Добавить суперадминистратора
          <input className="form-input" style={{ width: '100%', marginTop: 8 }} aria-label="Поиск пользователя" disabled={busy}
            value={query} onChange={e => setQuery(e.target.value)} placeholder="Имя, @username или Telegram ID" />
        </label>
        <p style={{ fontSize: 12, color: '#777', lineHeight: 1.5 }}>Сначала попросите человека открыть мини-приложение через бота. Даже если вход пока запрещён, после этого он появится в поиске.</p>
        {searching && <p role="status">Ищем...</p>}
        {searchError && <div role="alert">{searchError}</div>}
        {searchDone && !users.length && <p>Пользователь не найден.</p>}
        {users.map(user => <button key={user.telegram_user_id} className="btn btn-secondary" style={{ width: '100%', marginBottom: 6, textAlign: 'left' }}
          disabled={busy || user.is_superadmin} onClick={() => setSelected(user)}>
          {name(user)} · ID {user.telegram_user_id}{user.is_superadmin ? ' · уже суперадминистратор' : ''}
        </button>)}
        {selected && <div style={{ padding: 12, marginTop: 12, borderRadius: 10, background: '#f8eeee' }}>
          <strong>{name(selected)} · ID {selected.telegram_user_id}</strong>
          <p style={{ fontSize: 13 }}>{selected.revoke ? 'Снять глобальные права? Права администратора своего чата сохранятся, если они есть.' : 'Этот человек получит полные права управления театром.'}</p>
          <button className="btn btn-primary" disabled={busy} onClick={() => change(selected, !selected.revoke)}>{busy ? 'Сохраняем...' : selected.revoke ? 'Подтвердить снятие' : 'Назначить суперадминистратором'}</button>
          <button className="btn btn-secondary" style={{ margin: '6px 0 0 6px' }} disabled={busy} onClick={() => setSelected(null)}>Отмена</button>
        </div>}
        {!!data.audit?.length && <details style={{ marginTop: 16, fontSize: 12 }}>
          <summary>История изменений</summary>
          <ul>{data.audit.map(entry => <li key={entry.id} style={{ marginTop: 8 }}>
            {new Date(entry.created_at).toLocaleString('ru-RU')} · {entry.action === 'revoke' ? 'Права сняты' : entry.action === 'bootstrap' ? 'Первый администратор' : 'Права выданы'}: {name(entry)} · автор ID {entry.actor_id}
          </li>)}</ul>
        </details>}
      </>}
    </div>
  </section>;
}
