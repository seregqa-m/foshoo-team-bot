import React, { useEffect, useState } from 'react';
import client from '../api/client';

const endpoint = '/api/admin/theater';
const errorText = error => typeof error.response?.data?.detail === 'string'
  ? error.response.data.detail : 'Не удалось выполнить действие. Обновите список и попробуйте ещё раз.';

function ShowEditor({ show, chats, busy, save }) {
  const [name, setName] = useState(show.name);
  const [chatId, setChatId] = useState(String(show.telegram_chat_id ?? ''));
  const changed = name.trim() !== show.name || chatId !== String(show.telegram_chat_id ?? '');
  return <form aria-label={`Настройки спектакля ${show.name}`} onSubmit={event => {
    event.preventDefault();
    if (changed && name.trim()) save(show, name.trim(), chatId ? Number(chatId) : null);
  }} style={{ borderTop: '1px solid #eee', padding: '14px 0' }}>
    <label>Название спектакля
      <input className="form-input" aria-label={`Название: ${show.name}`} style={{ width: '100%', margin: '6px 0 12px' }}
        disabled={busy} value={name} maxLength={200} required onChange={event => setName(event.target.value)} />
    </label>
    <label>Чат для напоминаний
      <select className="select-input" aria-label={`Чат: ${show.name}`} style={{ width: '100%', margin: '6px 0 12px' }}
        disabled={busy} value={chatId} onChange={event => setChatId(event.target.value)}>
        <option value="">Не назначен</option>
        {chats.map(chat => <option key={chat.telegram_chat_id} value={String(chat.telegram_chat_id)}>
          {chat.title} · {chat.telegram_chat_id}
        </option>)}
      </select>
    </label>
    <button type="submit" className="btn btn-primary" disabled={busy || !changed || !name.trim()}>Сохранить {show.name}</button>
  </form>;
}

export default function TheaterPanel() {
  const [data, setData] = useState(null);
  const [name, setName] = useState('');
  const [chatId, setChatId] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true); setData(null);
    client.get(endpoint)
      .then(({ data: result }) => { if (active) setData(result); })
      .catch(e => { if (active) setError(errorText(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [revision]);

  const run = async (operation, success) => {
    if (busy || loading) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await operation();
      setMessage(success(result.data));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false); setRevision(value => value + 1);
    }
  };

  const save = (show, value, target) => run(() => client.put(`${endpoint}/shows/${show.id}`, {
    name: value, telegram_chat_id: target, expected_revision: show.revision,
  }), () => `Настройки «${value}» сохранены.`);

  return <section aria-label="Спектакли и чаты" className="card-white" style={{ padding: 16, marginTop: 16 }}>
    <h3 style={{ marginTop: 0 }}>Спектакли и чаты</h3>
    <p style={{ fontSize: 13 }}>Общий справочник театра. Назначать чаты может только суперадминистратор.</p>
    <p style={{ fontSize: 13 }}>Сейчас здесь подготавливаются маршруты. Автоматическая отправка по ним будет подключена следующим этапом; действующие опросы продолжают работать по прежним настройкам.</p>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {message && <div className="alert alert-success" role="status">{message}</div>}
    {loading && <p role="status">Загружаем спектакли и чаты…</p>}
    <button className="btn btn-secondary" disabled={busy || loading} onClick={() => { setError(''); setRevision(value => value + 1); }}>Обновить спектакли и чаты</button>
    {data && <>
      <form aria-label="Добавить чат" onSubmit={event => {
        event.preventDefault();
        const id = Number(chatId);
        if (!/^-\d+$/.test(chatId.trim()) || !Number.isSafeInteger(id) || id >= 0 || id < -(2 ** 52 - 1)) {
          setError('Введите отрицательный числовой ID группы Telegram.'); return;
        }
        run(() => client.post(`${endpoint}/chats`, { telegram_chat_id: id }), result => {
          setChatId(''); return `Чат «${result.title}» проверен и добавлен.`;
        });
      }} style={{ marginTop: 18 }}>
        <label>ID чата Telegram
          <input className="form-input" aria-label="ID чата Telegram" value={chatId} required disabled={busy}
            style={{ width: '100%', margin: '6px 0' }} placeholder="-100…" onChange={event => setChatId(event.target.value)} />
        </label>
        <p style={{ fontSize: 12 }}>Добавьте бота в группу и назначьте администратором с правом закреплять сообщения. Проверка не отправляет сообщений и не выдаёт участникам новые права.</p>
        <button type="submit" className="btn btn-secondary" disabled={busy || !chatId.trim()}>Проверить и добавить чат</button>
      </form>
      <form aria-label="Добавить спектакль" onSubmit={event => {
        event.preventDefault();
        if (name.trim()) run(() => client.post(`${endpoint}/shows`, { name: name.trim() }), result => {
          setName(''); return result.added ? 'Спектакль добавлен.' : 'Этот спектакль уже есть в справочнике.';
        });
      }} style={{ margin: '18px 0' }}>
        <label>Новый спектакль
          <input className="form-input" aria-label="Новый спектакль" value={name} required maxLength={200} disabled={busy}
            style={{ width: '100%', margin: '6px 0' }} onChange={event => setName(event.target.value)} />
        </label>
        <button type="submit" className="btn btn-secondary" disabled={busy || !name.trim()}>Добавить спектакль</button>
      </form>
      <button className="btn btn-secondary" disabled={busy} onClick={() => run(
        () => client.post(`${endpoint}/shows/import`), result => `Добавлено спектаклей из таблицы: ${result.added}.`
      )}>Импортировать спектакли из таблицы</button>
      <p style={{ fontSize: 12 }}>Импорт добавляет недостающие названия и сохраняет настроенные чаты.</p>
      {!data.shows.length && <p>Спектаклей пока нет. Добавьте название или импортируйте из таблицы.</p>}
      {data.shows.map(show => <ShowEditor key={`${revision}:${show.id}`} show={show} chats={data.chats} busy={busy || loading} save={save} />)}
      {!!data.chats.length && <details style={{ marginTop: 12 }}>
        <summary>Проверенные чаты</summary>
        <ul>{data.chats.map(chat => <li key={chat.telegram_chat_id}>
          {chat.title} · {chat.telegram_chat_id} · проверен {new Date(chat.checked_at).toLocaleString('ru-RU')}
        </li>)}</ul>
      </details>}
      {!!data.audit.length && <details style={{ marginTop: 12 }}>
        <summary>История настроек спектаклей</summary>
        <ul>{data.audit.map(entry => <li key={entry.id} style={{ marginTop: 8, fontSize: 12 }}>
          {new Date(entry.created_at).toLocaleString('ru-RU')} · автор ID {entry.actor_id} · {
            entry.action === 'shows_added' ? `Добавлены: ${entry.details.names.join(', ')}`
              : entry.action === 'chat_registered' ? `Добавлен чат: ${entry.details.title}`
                : `Спектакль: ${entry.details.name}; чат: ${entry.details.old_chat_id ?? 'не назначен'} → ${entry.details.chat_id ?? 'не назначен'}`
          }
        </li>)}</ul>
      </details>}
    </>}
  </section>;
}
