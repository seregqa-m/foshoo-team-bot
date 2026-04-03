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
        <div className="page-title">Уведомления</div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {saved && <div className="alert alert-success">Настройки сохранены</div>}

      <div className="section-label">Типы уведомлений</div>
      <div className="card-white">
        <div className="toggle-row">
          <span className="toggle-label">📊 Напоминания об опросах</span>
          <Toggle checked={settings.poll_reminders_enabled} onChange={() => toggle('poll_reminders_enabled')} />
        </div>
        <div className="toggle-row">
          <span className="toggle-label">💰 Напоминания о платежах</span>
          <Toggle checked={settings.payment_reminders_enabled} onChange={() => toggle('payment_reminders_enabled')} />
        </div>
        <div className="toggle-row">
          <span className="toggle-label">📅 Напоминания о занятиях</span>
          <Toggle checked={settings.event_reminders_enabled} onChange={() => toggle('event_reminders_enabled')} />
        </div>
      </div>

      <div className="section-label">За сколько часов предупреждать</div>
      <div className="card-white" style={{ padding: '14px 16px' }}>
        <select
          className="select-input"
          value={settings.reminder_hours_before}
          onChange={e => { setSettings(s => ({ ...s, reminder_hours_before: parseInt(e.target.value) })); setSaved(false); }}
        >
          <option value="1">1 час</option>
          <option value="6">6 часов</option>
          <option value="12">12 часов</option>
          <option value="24">1 день</option>
          <option value="48">2 дня</option>
        </select>
      </div>

      <button className="btn btn-primary" style={{ width: '100%', padding: 14, fontSize: 15, marginTop: 8 }} onClick={handleSave}>
        Сохранить
      </button>
    </>
  );
}
