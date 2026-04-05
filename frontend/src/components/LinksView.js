import React, { useState, useEffect } from 'react';

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

export default function LinksView() {
  const [blocks, setBlocks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000'}/api/links`)
      .then(r => r.json())
      .then(data => { setBlocks(data.blocks || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  return (
    <>
      <div className="page-header">
        <div className="page-title">Ресурсы</div>
      </div>
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
