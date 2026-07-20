import React, { useState, useEffect, useRef } from 'react';

const API_BASE = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';
const AFISHA_SITE_URL = 'https://foshoo-theatre.ru/afisha';

function openUrl(url) {
  if (window.Telegram?.WebApp?.openLink) {
    window.Telegram.WebApp.openLink(url);
  } else {
    window.open(url, '_blank', 'noreferrer');
  }
}

function LinkItem({ item }) {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '11px 16px' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: '#111' }}>{item.label}</div>
          {item.sublabel && (
            <div style={{ fontSize: 11, color: '#999', marginTop: 1 }}>{item.sublabel}</div>
          )}
        </div>
        {item.instruction && (
          <button
            onClick={() => setOpen(s => !s)}
            style={{
              background: 'none', border: '1px solid #ddd', borderRadius: 6,
              padding: '3px 8px', fontSize: 11, color: '#888', cursor: 'pointer',
              flexShrink: 0, lineHeight: 1.4,
            }}
          >
            {open ? 'скрыть' : 'как?'}
          </button>
        )}
        <button
          onClick={() => openUrl(item.url)}
          style={{
            background: '#f5f5f5', border: 'none', borderRadius: 8,
            padding: '7px 12px', fontSize: 15, cursor: 'pointer', flexShrink: 0, color: '#333',
          }}
        >
          →
        </button>
      </div>
      {open && item.instruction && (
        <div style={{
          margin: '0 16px 10px',
          background: '#f8f8f8',
          borderLeft: '3px solid #ddd',
          borderRadius: '0 6px 6px 0',
          padding: '8px 12px',
          fontSize: 12,
          color: '#555',
          lineHeight: 1.7,
          whiteSpace: 'pre-line',
        }}>
          {item.instruction}
        </div>
      )}
    </div>
  );
}

function LinksBlock({ block }) {
  return (
    <div className="card-white" style={{ padding: 0, marginBottom: 12, overflow: 'hidden' }}>
      <div style={{ padding: '11px 16px 9px', borderBottom: '1px solid #f0f0f0' }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#888', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {block.title}
        </div>
      </div>
      {block.items.map((item, i) => (
        <div key={i} style={{ borderBottom: i < block.items.length - 1 ? '1px solid #f5f5f5' : 'none' }}>
          <LinkItem item={item} />
        </div>
      ))}
    </div>
  );
}

function AfishaUpload() {
  const [file, setFile] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);

  const pickFile = () => {
    setError('');
    setDone(false);
    inputRef.current?.click();
  };

  const handleFileChange = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setConfirmOpen(true);
    e.target.value = '';
  };

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
      setFile(null);
      setDone(true);
      // Открываем сайт автоматически
      openUrl(AFISHA_SITE_URL);
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  };

  const cancel = () => {
    setConfirmOpen(false);
    setFile(null);
    setDone(false);
    setError('');
  };

  return (
    <>
      <div className="card-white" style={{ padding: '12px 16px', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: '#111' }}>Афиша на сайте</div>
          <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>Загрузить новую афишу на foshoo-theatre.ru</div>
        </div>
        <button
          onClick={pickFile}
          style={{
            background: '#111', color: '#fff', border: 'none', borderRadius: 8,
            padding: '7px 14px', fontSize: 13, cursor: 'pointer', flexShrink: 0, fontWeight: 500,
          }}
        >
          Загрузить
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="image/*,.pdf"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
      </div>

      {confirmOpen && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1000, padding: '0 24px',
        }}>
          <div style={{
            background: '#fff', borderRadius: 16, padding: '24px 20px',
            width: '100%', maxWidth: 360, boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
          }}>
            {done ? (
              <>
                <div style={{ fontSize: 22, marginBottom: 8 }}>✓</div>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>Афиша обновлена</div>
                <div style={{ fontSize: 13, color: '#555', marginBottom: 20 }}>
                  Сайт должен открыться автоматически. Если нет — нажми кнопку.
                </div>
                <div style={{ display: 'flex', gap: 10 }}>
                  <button
                    onClick={cancel}
                    style={{
                      flex: 1, padding: '10px 0', borderRadius: 10,
                      border: '1px solid #ddd', background: '#fff',
                      fontSize: 14, cursor: 'pointer', color: '#555',
                    }}
                  >
                    Закрыть
                  </button>
                  <button
                    onClick={() => openUrl(AFISHA_SITE_URL)}
                    style={{
                      flex: 1, padding: '10px 0', borderRadius: 10, border: 'none',
                      background: '#111', color: '#fff', fontSize: 14, cursor: 'pointer', fontWeight: 500,
                    }}
                  >
                    Открыть сайт
                  </button>
                </div>
              </>
            ) : (
              <>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Обновить афишу?</div>
                <div style={{ fontSize: 13, color: '#444', marginBottom: 6, wordBreak: 'break-all' }}>
                  Файл <b>{file?.name}</b> станет новой афишей, текущая — архивной.
                </div>
                <div style={{ fontSize: 12, color: '#999', marginBottom: 20 }}>
                  После загрузки откроем сайт для проверки.
                </div>
                {error && (
                  <div style={{ fontSize: 12, color: '#c0392b', marginBottom: 12, background: '#fff5f5', borderRadius: 8, padding: '8px 10px' }}>
                    {error}
                  </div>
                )}
                <div style={{ display: 'flex', gap: 10 }}>
                  <button
                    onClick={cancel}
                    disabled={uploading}
                    style={{
                      flex: 1, padding: '10px 0', borderRadius: 10,
                      border: '1px solid #ddd', background: '#fff',
                      fontSize: 14, cursor: uploading ? 'not-allowed' : 'pointer', color: '#555',
                    }}
                  >
                    Отмена
                  </button>
                  <button
                    onClick={doUpload}
                    disabled={uploading}
                    style={{
                      flex: 1, padding: '10px 0', borderRadius: 10, border: 'none',
                      background: uploading ? '#999' : '#111', color: '#fff',
                      fontSize: 14, cursor: uploading ? 'not-allowed' : 'pointer', fontWeight: 500,
                    }}
                  >
                    {uploading ? 'Загрузка…' : 'Загрузить'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

export default function LinksView() {
  const [blocks, setBlocks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/links`)
      .then(r => r.json())
      .then(data => { setBlocks(data.blocks || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  return (
    <>
      <div className="page-header">
        <div className="page-title">Ресурсы</div>
      </div>
      <AfishaUpload />
      {loading ? (
        <div className="empty-state">Загрузка...</div>
      ) : blocks.length === 0 ? (
        <div className="empty-state">Нет данных — заполните backend/links.json</div>
      ) : (
        blocks.map(block => <LinksBlock key={block.id} block={block} />)
      )}
    </>
  );
}
