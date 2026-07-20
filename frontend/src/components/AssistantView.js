import React, { useState, useEffect, useRef, useCallback } from 'react';
import { assistantApi } from '../api/client';

const API_BASE = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';
const AFISHA_SITE_URL = 'https://foshoo-theatre.ru/afisha';

function openUrl(url) {
  if (window.Telegram?.WebApp?.openLink) {
    window.Telegram.WebApp.openLink(url);
  } else {
    window.open(url, '_blank', 'noreferrer');
  }
}

function useSessionId() {
  const [sid] = useState(() => {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    return `sess-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  });
  return sid;
}

function AfishaUploadCard({ preview, state, onDone, onCancel }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef(null);
  const finished = state && state !== 'pending';

  const doUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(`${API_BASE}/api/afisha/upload`, { method: 'POST', body: fd });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Ошибка ${res.status}`);
      }
      onDone(true);
      openUrl(AFISHA_SITE_URL);
    } catch (e) {
      setError(e.message);
      onDone(false);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className={`action-preview action-preview--${state || 'pending'}`}>
      <div className="action-preview__title">{preview.title}</div>
      <ul className="action-preview__lines">
        {(preview.lines || []).map((l, i) => <li key={i}>{l}</li>)}
      </ul>
      {!finished && (
        <>
          <div style={{ margin: '10px 0 6px' }}>
            <input
              ref={fileRef}
              type="file"
              accept="image/*,.pdf"
              style={{ display: 'none' }}
              onChange={e => { setFile(e.target.files?.[0] || null); e.target.value = ''; }}
            />
            <button
              className="btn-secondary"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
            >
              {file ? `📎 ${file.name}` : 'Выбрать файл'}
            </button>
          </div>
          {error && <div className="action-preview__warning">{error}</div>}
          <div className="action-preview__actions">
            <button
              className="btn-primary"
              onClick={doUpload}
              disabled={!file || uploading}
            >
              {uploading ? 'Загрузка…' : 'Загрузить'}
            </button>
            <button className="btn-secondary" onClick={onCancel}>Отмена</button>
          </div>
        </>
      )}
    </div>
  );
}

function ActionPreviewCard({ preview, toolName, state, onConfirm, onCancel, onAfishaResult }) {
  if (toolName === 'upload_afisha') {
    return (
      <AfishaUploadCard
        preview={preview}
        state={state}
        onDone={onAfishaResult}
        onCancel={onCancel}
      />
    );
  }

  const disabled = state && state !== 'pending';
  return (
    <div className={`action-preview action-preview--${state || 'pending'}`}>
      <div className="action-preview__title">{preview.title}</div>
      <ul className="action-preview__lines">
        {(preview.lines || []).map((l, i) => (
          <li key={i}>{l}</li>
        ))}
      </ul>
      {(preview.warnings || []).map((w, i) => (
        <div key={i} className="action-preview__warning">⚠️ {w}</div>
      ))}
      <div className="action-preview__actions">
        <button
          className="btn-primary"
          onClick={onConfirm}
          disabled={disabled}
        >
          {state === 'executing' ? 'Выполняю…'
            : state === 'done' ? 'Выполнено'
            : state === 'failed' ? 'Ошибка'
            : state === 'cancelled' ? 'Отменено'
            : 'Выполнить'}
        </button>
        {(!state || state === 'pending') && (
          <button className="btn-secondary" onClick={onCancel}>Отмена</button>
        )}
      </div>
    </div>
  );
}

function SettingsOverlay({ open, onClose, children }) {
  useEffect(() => {
    if (!open) return undefined;
    const onEsc = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onEsc);
    return () => document.removeEventListener('keydown', onEsc);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="settings-overlay">
      <div className="settings-overlay__header">
        <button className="settings-overlay__back" onClick={onClose} aria-label="Назад">←</button>
        <div className="settings-overlay__title">Настройки</div>
      </div>
      <div className="settings-overlay__body">{children}</div>
    </div>
  );
}

export default function AssistantView({ userId, username, renderSettings }) {
  const sessionId = useSessionId();
  const [messages, setMessages] = useState([]); // {role, content, error?}
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [hints, setHints] = useState([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
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
    // История для LLM — только текстовые роли, без action-preview штук
    const historyForApi = messages
      .filter(m => (m.role === 'user' || m.role === 'assistant') && m.content)
      .map(m => ({ role: m.role, content: m.content }));
    setMessages(m => [...m, userMsg]);
    setSending(true);
    try {
      const res = await assistantApi.chat({
        userId,
        username,
        sessionId,
        message: msg,
        history: historyForApi,
      });
      setMessages(m => [
        ...m,
        {
          role: 'assistant',
          content: res.reply,
          pendingAction: res.pending_action || null,
          actionState: res.pending_action ? 'pending' : null,
        },
      ]);
    } catch (e) {
      const detail = e.response?.data?.detail || 'Не получилось получить ответ';
      setMessages(m => [...m, { role: 'assistant', content: detail, error: true }]);
    } finally {
      setSending(false);
    }
  };

  const confirmAction = async (idx) => {
    const target = messages[idx];
    if (!target?.pendingAction) return;
    setMessages(m => m.map((x, i) => (i === idx ? { ...x, actionState: 'executing' } : x)));
    try {
      const res = await assistantApi.execute({
        userId,
        actionToken: target.pendingAction.action_token,
      });
      const okText = res.success ? 'Готово ✅' : `Не получилось: ${res.message || ''}`;
      setMessages(m => m.map((x, i) => (i === idx ? { ...x, actionState: res.success ? 'done' : 'failed' } : x)));
      setMessages(m => [...m, { role: 'assistant', content: okText }]);

      if (res.success) {
        // Автоматически продолжаем диалог — LLM предложит следующую операцию если она была.
        // Описываем что именно выполнено, чтобы LLM не повторила то же самое.
        const preview = target.pendingAction?.preview || {};
        const doneNote = `[Выполнено: ${preview.title || 'действие'} — ${(preview.lines || []).join('; ')}]`;
        const historySnapshot = [
          ...messages
            .filter(m => (m.role === 'user' || m.role === 'assistant') && m.content)
            .map(m => ({ role: m.role, content: m.content })),
          { role: 'assistant', content: doneNote },
        ];
        setSending(true);
        try {
          const followUp = await assistantApi.chat({
            userId, username, sessionId,
            message: 'Выполни следующую операцию из предыдущего запроса — вызови tool немедленно.',
            history: historySnapshot,
          });
          setMessages(m => [...m, {
            role: 'assistant',
            content: followUp.reply,
            pendingAction: followUp.pending_action || null,
            actionState: followUp.pending_action ? 'pending' : null,
          }]);
        } catch (_) {
          // автопродолжение некритично — молча игнорируем
        } finally {
          setSending(false);
        }
      }
    } catch (e) {
      const detail = e.response?.data?.detail || 'Не удалось выполнить';
      setMessages(m => m.map((x, i) => (i === idx ? { ...x, actionState: 'failed' } : x)));
      setMessages(m => [...m, { role: 'assistant', content: detail, error: true }]);
    }
  };

  const cancelAction = (idx) => {
    setMessages(m => m.map((x, i) => (i === idx ? { ...x, actionState: 'cancelled' } : x)));
    setMessages(m => [...m, { role: 'assistant', content: 'Ок, отменил.' }]);
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
      {renderSettings && empty && (
        <button
          className="assistant-gear"
          onClick={() => setSettingsOpen(true)}
          aria-label="Настройки"
        >
          ⚙️
        </button>
      )}
      <SettingsOverlay open={settingsOpen} onClose={() => setSettingsOpen(false)}>
        {renderSettings && renderSettings()}
      </SettingsOverlay>
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
              <React.Fragment key={i}>
                {m.content && (
                  <div className={`chat-bubble ${m.role === 'user' ? 'chat-bubble--user' : 'chat-bubble--assistant'} ${m.error ? 'chat-bubble--error' : ''}`}>
                    {m.content}
                  </div>
                )}
                {m.pendingAction && (
                  <ActionPreviewCard
                    preview={m.pendingAction.preview}
                    toolName={m.pendingAction.tool_name}
                    state={m.actionState}
                    onConfirm={() => confirmAction(i)}
                    onCancel={() => cancelAction(i)}
                    onAfishaResult={(success) => {
                      setMessages(prev => prev.map((x, j) =>
                        j === i ? { ...x, actionState: success ? 'done' : 'failed' } : x
                      ));
                      setMessages(prev => [...prev, {
                        role: 'assistant',
                        content: success ? 'Афиша обновлена ✅ Сайт должен открыться автоматически.' : 'Не удалось загрузить файл.',
                        error: !success,
                      }]);
                    }}
                  />
                )}
              </React.Fragment>
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
