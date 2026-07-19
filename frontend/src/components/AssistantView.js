import React, { useState, useEffect, useRef, useCallback } from 'react';
import { assistantApi } from '../api/client';

function useSessionId() {
  const [sid] = useState(() => {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    return `sess-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  });
  return sid;
}

export default function AssistantView({ userId, username }) {
  const sessionId = useSessionId();
  const [messages, setMessages] = useState([]); // {role, content, error?}
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [hints, setHints] = useState([]);
  const listRef = useRef(null);
  const textareaRef = useRef(null);

  const loadHints = useCallback(async () => {
    try {
      const h = await assistantApi.hints();
      setHints(h);
    } catch (e) {
      // не критично
    }
  }, []);

  useEffect(() => { loadHints(); }, [loadHints]);

  // ротация подсказок каждые 6 сек, пока диалог пустой
  useEffect(() => {
    if (messages.length > 0) return undefined;
    const id = setInterval(loadHints, 6000);
    return () => clearInterval(id);
  }, [messages.length, loadHints]);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages.length]);

  // auto-grow textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }, [input]);

  const send = async (text) => {
    const msg = (text ?? input).trim();
    if (!msg || sending) return;
    setInput('');
    const userMsg = { role: 'user', content: msg };
    const historyForApi = messages.map(m => ({ role: m.role, content: m.content }));
    setMessages(m => [...m, userMsg]);
    setSending(true);
    try {
      const res = await assistantApi.chat({
        userId,
        sessionId,
        message: msg,
        history: historyForApi,
      });
      setMessages(m => [...m, { role: 'assistant', content: res.reply }]);
    } catch (e) {
      const detail = e.response?.data?.detail || 'Не получилось получить ответ';
      setMessages(m => [...m, { role: 'assistant', content: detail, error: true }]);
    } finally {
      setSending(false);
    }
  };

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const applyHint = (h) => {
    setInput(h);
    textareaRef.current?.focus();
  };

  const empty = messages.length === 0;

  return (
    <div className={`assistant ${empty ? 'assistant-empty' : 'assistant-chat'}`}>
      {empty ? (
        <div className="assistant-landing">
          <div className="assistant-hero">
            <div className="assistant-logo">🎭</div>
            <h1 className="assistant-title">Помощник FoShoo</h1>
            <p className="assistant-subtitle">
              Опиши что хочешь сделать — я разберусь. Расписание, финансы, опросы.
            </p>
          </div>
          <div className="assistant-input-wrap assistant-input-wrap--landing">
            <textarea
              ref={textareaRef}
              className="assistant-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder="Например: вчера потратил 500 на реквизит"
              rows={1}
            />
            <button
              className="assistant-send"
              onClick={() => send()}
              disabled={sending || !input.trim()}
              aria-label="Отправить"
            >
              {sending ? '…' : '↑'}
            </button>
          </div>
          <div className="assistant-hints">
            {hints.map((h, i) => (
              <button key={i} className="assistant-hint" onClick={() => applyHint(h)}>
                {h}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className="assistant-messages" ref={listRef}>
            {messages.map((m, i) => (
              <div key={i} className={`chat-bubble ${m.role === 'user' ? 'chat-bubble--user' : 'chat-bubble--assistant'} ${m.error ? 'chat-bubble--error' : ''}`}>
                {m.content}
              </div>
            ))}
            {sending && (
              <div className="chat-bubble chat-bubble--assistant chat-bubble--typing">
                <span></span><span></span><span></span>
              </div>
            )}
          </div>
          <div className="assistant-input-wrap assistant-input-wrap--sticky">
            <textarea
              ref={textareaRef}
              className="assistant-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder="Продолжи…"
              rows={1}
            />
            <button
              className="assistant-send"
              onClick={() => send()}
              disabled={sending || !input.trim()}
              aria-label="Отправить"
            >
              {sending ? '…' : '↑'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
