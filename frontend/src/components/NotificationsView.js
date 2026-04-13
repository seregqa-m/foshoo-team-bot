import React, { useState, useEffect } from 'react';
import client from '../api/client';

function Toggle({ checked, onChange }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={onChange} />
      <div className="toggle-track" />
    </label>
  );
}

export default function NotificationsView({ userId }) {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [showNames, setShowNames] = useState([]);

  useEffect(() => {
    fetch(`${process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000'}/api/sheets/shows`)
      .then(r => r.json())
      .then(data => setShowNames(data.shows || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!userId) { setLoading(false); return; }
    client.get('/api/notifications/settings', { params: { user_id: userId } })
      .then(r => setSettings(r.data))
      .catch(() => setError('Не удалось загрузить настройки'))
      .finally(() => setLoading(false));
  }, [userId]);

  const toggle = key => {
    setSettings(s => ({ ...s, [key]: !s[key] }));
    setSaved(false);
  };

  const handleSave = async () => {
    try {
      await client.post('/api/notifications/settings', settings, { params: { user_id: userId } });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      setError(null);
    } catch {
      setError('Ошибка при сохранении');
    }
  };

  if (loading) return <div className="empty-state">Загрузка...</div>;

  if (!userId) return (
    <div className="empty-state">Откройте приложение через Telegram чтобы управлять уведомлениями.</div>
  );

  if (!settings) return <div className="empty-state">{error || 'Ошибка загрузки'}</div>;

  return (
    <>
      <div className="page-header">
        <div className="page-title">Настройки</div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {saved && <div className="alert alert-success">Настройки сохранены</div>}

      <div className="section-label">Текущий репетируемый спектакль</div>
      <div className="card-white" style={{ padding: '14px 16px' }}>
        <div style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
          Тегаются только задействованные в нём актёры. Если не выбран — тегаются все.
        </div>
        <select
          className="select-input"
          style={{ width: '100%' }}
          value={settings.current_show ?? ''}
          onChange={e => { setSettings(s => ({ ...s, current_show: e.target.value })); setSaved(false); }}
        >
          <option value="">— все актёры —</option>
          {showNames.map(name => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      </div>

      <div className="section-label">Авто-создание опросов</div>
      <div className="card-white">
        <div className="toggle-row">
          <span className="toggle-label">📊 Авто-создание опросов</span>
          <Toggle checked={settings.poll_reminders_enabled} onChange={() => toggle('poll_reminders_enabled')} />
        </div>
      </div>

      <div className="section-label">Создавать опрос за N дней до события</div>
      <div className="card-white" style={{ padding: '14px 16px', display: 'flex', gap: 12, alignItems: 'center' }}>
        <select
          className="select-input"
          style={{ flex: 1 }}
          value={settings.reminder_days_before ?? 3}
          onChange={e => { setSettings(s => ({ ...s, reminder_days_before: parseInt(e.target.value) })); setSaved(false); }}
        >
          <option value="1">1 день</option>
          <option value="2">2 дня</option>
          <option value="3">3 дня</option>
          <option value="5">5 дней</option>
          <option value="7">7 дней</option>
        </select>
        <span style={{ fontSize: 13, color: '#666' }}>в</span>
        <input
          type="time"
          className="form-input"
          style={{ width: 100 }}
          value={settings.reminder_time ?? '18:00'}
          onChange={e => { setSettings(s => ({ ...s, reminder_time: e.target.value })); setSaved(false); }}
        />
      </div>
      <div style={{ fontSize: 12, color: '#888', padding: '4px 4px 0' }}>
        Напоминание отправляется автоматически за 1 день до события
      </div>

      <div className="section-label" style={{ marginTop: 16 }}>Основная группа</div>
      <div className="card-white" style={{ padding: '14px 16px' }}>
        <div style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
          Подстрока в названии события для фильтрации и авто-опросов
        </div>
        <input
          type="text"
          className="form-input"
          style={{ width: '100%' }}
          value={settings.troupe_filter ?? 'труппа 1'}
          onChange={e => { setSettings(s => ({ ...s, troupe_filter: e.target.value })); setSaved(false); }}
        />
      </div>

      <button className="btn btn-primary" style={{ width: '100%', padding: 14, fontSize: 15, marginTop: 8 }} onClick={handleSave}>
        Сохранить
      </button>
    </>
  );
}
