import React, { useEffect, useState } from 'react';
import client from '../api/client';
import './TheaterPanel.css';

const endpoint = '/api/admin/theater';
const errorText = error => typeof error.response?.data?.detail === 'string'
  ? error.response.data.detail : 'Не удалось сохранить. Попробуйте ещё раз.';

function ShowRow({ show, busy, save }) {
  const [name, setName] = useState(show.name);
  const [chatId, setChatId] = useState(String(show.telegram_chat_id ?? ''));
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const formId = `show-chat-${show.id}`;
  useEffect(() => {
    setName(show.name);
    setChatId(String(show.telegram_chat_id ?? ''));
  }, [show.name, show.telegram_chat_id, show.revision]);
  const changed = name.trim() !== show.name || chatId.trim() !== String(show.telegram_chat_id ?? '');

  const submit = async event => {
    event.preventDefault();
    if (busy || !changed || !name.trim()) return;
    setError(''); setSaved(false);
    const value = chatId.trim();
    const id = value ? Number(value) : null;
    if (value && (!/^-\d+$/.test(value) || !Number.isSafeInteger(id) || id >= 0 || id < -(2 ** 52 - 1))) {
      setError('Введите ID группы: отрицательное целое число.');
      return;
    }
    try {
      await save(show, name.trim(), id);
      setSaved(true);
    } catch (e) { setError(errorText(e)); }
  };

  return <tr>
    <td>
      <input className="form-input" aria-label={`Название: ${show.name}`} form={formId}
        value={name} required maxLength={200} disabled={busy}
        onChange={event => { setName(event.target.value); setSaved(false); }} />
    </td>
    <td>
      <form id={formId} aria-label={`Настройки спектакля ${show.name}`} onSubmit={submit}>
        <input className="form-input" aria-label={`ID чата: ${show.name}`} value={chatId}
          placeholder="Не назначен" disabled={busy} autoComplete="off" spellCheck={false}
          onChange={event => { setChatId(event.target.value); setSaved(false); }} />
        <button className="btn btn-secondary" type="submit" disabled={busy || !changed || !name.trim()}>Сохранить</button>
        {error && <div className="theater-table__error" role="alert">{error}</div>}
        {saved && <div className="theater-table__saved" role="status">Сохранено</div>}
      </form>
    </td>
  </tr>;
}

export default function TheaterPanel() {
  const [data, setData] = useState(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    client.get(endpoint)
      .then(({ data: result }) => { if (active) setData(result); })
      .catch(e => { if (active) { setError(errorText(e)); setData(null); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);

  const run = async (operation, success) => {
    if (busy || loading) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await operation();
      setMessage(success(result.data));
      setReload(value => value + 1);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };

  const save = async (show, value, target) => {
    setBusy(true);
    try {
      const { data: updated } = await client.put(`${endpoint}/shows/${show.id}`, {
        name: value, telegram_chat_id: target, expected_revision: show.revision,
      });
      setData(previous => ({ ...previous, shows: previous.shows.map(item => item.id === show.id ? updated : item) }));
    } catch (e) {
      if (e.response?.status === 409) setReload(value => value + 1);
      throw e;
    } finally { setBusy(false); }
  };

  return <section aria-label="Спектакли и чаты" className="card-white theater-panel">
    <h3>Спектакли и чаты</h3>
    <p>Укажите ID чата напротив спектакля и сохраните строку. Пустое поле снимает привязку.</p>
    <p>Бот должен быть администратором группы с правом закреплять сообщения.</p>
    <p className="theater-panel__note">Опросы репетиций и напоминания отправляются в чат указанного спектакля. В названии репетиции укажите спектакль и [Реп], например «Урод [Реп]».</p>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {message && <div className="alert alert-success" role="status">{message}</div>}
    {loading && <p role="status">Загружаем спектакли…</p>}
    {data && <>
      <button className="btn btn-secondary" disabled={busy || loading} onClick={() => run(
        () => client.post(`${endpoint}/shows/import`), result => `Добавлено спектаклей: ${result.added}.`
      )}>Импортировать спектакли из таблицы</button>
      <table className="theater-table" aria-label="Спектакли и ID чатов">
        <thead><tr><th scope="col">Спектакль</th><th scope="col">ID чата</th></tr></thead>
        <tbody>
          {data.shows.map(show => <ShowRow key={show.id} show={show} busy={busy || loading} save={save} />)}
          {!data.shows.length && <tr><td colSpan={2}>Импортируйте спектакли из таблицы или добавьте название ниже.</td></tr>}
        </tbody>
      </table>
      <details className="theater-panel__add">
        <summary>Добавить спектакль</summary>
        <form aria-label="Добавить спектакль" onSubmit={event => {
          event.preventDefault();
          if (name.trim()) run(() => client.post(`${endpoint}/shows`, { name: name.trim() }), result => {
            setName(''); return result.added ? 'Спектакль добавлен.' : 'Этот спектакль уже есть в таблице.';
          });
        }}>
          <input className="form-input" aria-label="Новый спектакль" value={name} required maxLength={200}
            placeholder="Название спектакля" disabled={busy || loading} onChange={event => setName(event.target.value)} />
          <button type="submit" className="btn btn-secondary" disabled={busy || loading || !name.trim()}>Добавить</button>
        </form>
      </details>
    </>}
    {error && <button className="btn btn-secondary" disabled={busy || loading}
      onClick={() => setReload(value => value + 1)}>Повторить загрузку</button>}
  </section>;
}
