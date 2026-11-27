import React, { useEffect, useRef, useState } from 'react';
import client from '../api/client';

const errorText = e => typeof e.response?.data?.detail === 'string' ? e.response.data.detail : 'Не удалось проверить отправку. Повторная проверка не создаст копию сообщения.';

export default function RepertoireShare({ data, variant, onClose }) {
  const [chats, setChats] = useState([]);
  const [chatId, setChatId] = useState('');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const guard = useRef(false);
  const panel = useRef(null);
  useEffect(() => {
    let active = true;
    panel.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    client.get('/api/planning/repertoire/chats').then(({ data: result }) => {
      if (active) { setChats(result.chats); if (result.warning) setError(result.warning); }
    }).catch(e => { if (active) setError(errorText(e)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, []);
  const prepare = async () => {
    if (guard.current || !chatId) return;
    guard.current = true; setBusy(true); setError(''); setPreview(null);
    try {
      const { data: result } = await client.post('/api/planning/repertoire/share/preview', {
        month: data.month, search_id: data.search_id, variant_id: variant.id, chat_id: Number(chatId),
        expected_fingerprint: data.fingerprint, expected_revision: data.revision,
      });
      setPreview(result);
    } catch (e) { setError(errorText(e)); }
    finally { guard.current = false; setBusy(false); }
  };
  const send = async () => {
    if (guard.current || !preview) return;
    guard.current = true; setBusy(true); setError('');
    try {
      const { data: result } = await client.post('/api/planning/repertoire/share/send', { preview_id: preview.id });
      setPreview(result);
    } catch (e) { setError(errorText(e)); }
    finally { guard.current = false; setBusy(false); }
  };
  const uncertain = ['sending', 'unknown'].includes(preview?.status);
  return <section ref={panel} className="repertoire-share" aria-labelledby="repertoire-share-title">
    <h3 id="repertoire-share-title">План на согласование</h3>
    <p className="repertoire-note">В чат уйдёт картинка календаря выбранного варианта со всеми ручными правками дат и времени. Отправка не назначает показы.</p>
    <label className="repertoire-field">Чат<select className="select-input" aria-label="Чат для согласования" value={chatId} disabled={busy} onChange={e => { setChatId(e.target.value); setPreview(null); setError(''); }}>
      <option value="">Выберите чат</option>{chats.map(chat => <option key={chat.id} value={chat.id}>{chat.title}</option>)}
    </select></label>
    {!busy && !chats.length && <p className="repertoire-note">Нет доступных групп. Нужен подключённый чат и право администратора на отправку.</p>}
    {error && <p className="alert alert-error" role="alert">{error}</p>}
    {preview && <>
      <p><strong>{preview.chat_title}</strong></p>
      {preview.image ? <>
        <img className="repertoire-share-image" src={preview.image} alt="Календарь афиши для отправки в чат" />
        <a href={preview.image} download={`afisha-${data.month}.png`}>Скачать календарь</a>
        <p className="repertoire-note">{preview.caption}</p>
        <details><summary>Даты и замечания к плану</summary><pre className="repertoire-message">{preview.text}</pre></details>
      </> : <pre className="repertoire-message">{preview.text}</pre>}
      {preview.status === 'sent' && <p role="status">План отправлен.{preview.link && <> <a href={preview.link} target="_blank" rel="noreferrer">Открыть сообщение</a></>}</p>}
      {uncertain && <p role="status">Telegram не подтвердил доставку. Проверьте чат: повторная отправка заблокирована, чтобы не создать дубль.</p>}
      {preview.status === 'failed' && <p role="alert">{preview.error || 'Telegram отклонил отправку. Можно повторить после устранения причины.'}</p>}
    </>}
    <div className="repertoire-actions">
      {!preview && <button type="button" className="btn btn-primary" disabled={busy || !chatId} onClick={prepare}>{busy ? 'Загружаем…' : 'Предпросмотр сообщения'}</button>}
      {preview && ['preview', 'failed'].includes(preview.status) && <button type="button" className="btn btn-primary" disabled={busy} onClick={send}>{busy ? 'Отправляем…' : 'Отправить на согласование'}</button>}
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>Закрыть</button>
    </div>
  </section>;
}
