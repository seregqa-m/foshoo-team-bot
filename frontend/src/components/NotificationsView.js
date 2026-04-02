import React, { useState, useEffect } from 'react';
import client from '../api/client';

function NotificationsView({ userId }) {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (userId) {
      fetchSettings();
    }
  }, [userId]);

  const fetchSettings = async () => {
    try {
      setLoading(true);
      const response = await client.get('/api/notifications/settings', {
        params: { user_id: userId },
      });
      setSettings(response.data);
    } catch (err) {
      console.error('Failed to fetch settings:', err);
      setError('Ошибка при загрузке настроек');
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = (key) => {
    setSettings((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
    setSaved(false);
  };

  const handleHoursChange = (value) => {
    setSettings((prev) => ({
      ...prev,
      reminder_hours_before: parseInt(value) || 24,
    }));
    setSaved(false);
  };

  const handleSave = async () => {
    try {
      await client.post('/api/notifications/settings', settings, {
        params: { user_id: userId },
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      console.error('Failed to save settings:', err);
      setError('Ошибка при сохранении настроек');
    }
  };

  if (loading) {
    return <div className="text-center mt-12">⏳ Загрузка настроек...</div>;
  }

  if (!settings) {
    return <div className="text-center text-secondary mt-12">Ошибка загрузки</div>;
  }

  return (
    <div>
      {error && (
        <div
          className="card"
          style={{ backgroundColor: '#f8d7da', borderColor: '#dc3545' }}
        >
          <div style={{ color: '#721c24' }}>{error}</div>
        </div>
      )}

      {saved && (
        <div
          className="card"
          style={{ backgroundColor: '#d4edda', borderColor: '#28a745' }}
        >
          <div style={{ color: '#155724' }}>✅ Настройки сохранены</div>
        </div>
      )}

      <div className="card">
        <div style={{ fontWeight: 'bold', fontSize: '14px', marginBottom: '12px' }}>
          🔔 Типы уведомлений
        </div>

        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '8px',
            cursor: 'pointer',
            marginBottom: '8px',
          }}
        >
          <input
            type="checkbox"
            checked={settings.poll_reminders_enabled}
            onChange={() => handleToggle('poll_reminders_enabled')}
            style={{ marginRight: '8px' }}
          />
          <span>📊 Напоминания об опросах</span>
        </label>

        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '8px',
            cursor: 'pointer',
            marginBottom: '8px',
          }}
        >
          <input
            type="checkbox"
            checked={settings.payment_reminders_enabled}
            onChange={() => handleToggle('payment_reminders_enabled')}
            style={{ marginRight: '8px' }}
          />
          <span>💰 Напоминания о платежах</span>
        </label>

        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '8px',
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={settings.event_reminders_enabled}
            onChange={() => handleToggle('event_reminders_enabled')}
            style={{ marginRight: '8px' }}
          />
          <span>📅 Напоминания о занятиях</span>
        </label>
      </div>

      <div className="card">
        <div style={{ fontWeight: 'bold', fontSize: '14px', marginBottom: '8px' }}>
          ⏱️ Время напоминания
        </div>
        <div style={{ fontSize: '12px', color: '#666', marginBottom: '8px' }}>
          За сколько часов до события отправлять уведомление?
        </div>
        <select
          value={settings.reminder_hours_before}
          onChange={(e) => handleHoursChange(e.target.value)}
          style={{
            width: '100%',
            padding: '8px',
            borderRadius: '4px',
            border: '1px solid #ccc',
            fontSize: '14px',
          }}
        >
          <option value="1">1 час</option>
          <option value="6">6 часов</option>
          <option value="12">12 часов</option>
          <option value="24">1 день</option>
          <option value="48">2 дня</option>
        </select>
      </div>

      <div style={{ padding: '0 8px' }}>
        <button
          className="btn btn-primary"
          onClick={handleSave}
          style={{ width: '100%' }}
        >
          💾 Сохранить
        </button>
      </div>
    </div>
  );
}

export default NotificationsView;
