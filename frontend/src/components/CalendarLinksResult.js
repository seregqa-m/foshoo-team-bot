import React, { useState } from 'react';

export default function CalendarLinksResult({ links }) {
  const [notice, setNotice] = useState('');
  const text = links.map(link => `${link.name}\n${link.url || 'Ссылка отключена'}`).join('\n\n');
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setNotice('Ссылки скопированы'); }
    catch { setNotice('Выделите и скопируйте ссылки из поля ниже.'); }
  };
  return <div className="chat-bubble chat-bubble--assistant" aria-label="Общие календарные ссылки">
    <p>Общие подписки по составам. Участникам не нужен вход в приложение.</p>
    <ul>{links.map(link => <li key={link.show_ids.join(',')}>
      {link.name}{' — '}{link.url
        ? <a href={link.webcal_url}>Подписаться</a> : 'Ссылка отключена'}
    </li>)}</ul>
    <p>Для Google Calendar: добавьте HTTPS-ссылку через «Другие календари → По URL» на компьютере. Новые события и изменения появятся после обновления подписки вашим календарём.</p>
    <textarea aria-label="Ссылки для отправки" readOnly value={text} rows={Math.min(12, links.length * 3)}
      style={{ width: '100%', boxSizing: 'border-box' }} onFocus={event => event.target.select()} />
    <button type="button" className="btn btn-secondary" onClick={copy}>Копировать все ссылки</button>
    {notice && <p role="status">{notice}</p>}
  </div>;
}
