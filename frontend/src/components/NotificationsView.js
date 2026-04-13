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

const API = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';

function AvailabilitySection({ showNames }) {
  const [campaign, setCampaign] = useState(undefined); // undefined=loading, null=none
  const [showForm, setShowForm] = useState(false);
  const [nextEvents, setNextEvents] = useState([]);
  const [selectedShows, setSelectedShows] = useState([]);
  const [selectedEvents, setSelectedEvents] = useState([]);
  const [missingDates, setMissingDates] = useState([]);
  const [nonVoters, setNonVoters] = useState(null);
  const [sending, setSending] = useState(false);
  const [formError, setFormError] = useState(null);

  const loadCampaign = () => {
    client.get('/api/availability/current')
      .then(r => setCampaign(r.data.campaign || null))
      .catch(() => setCampaign(null));
  };

  useEffect(() => { loadCampaign(); }, []);

  const openForm = () => {
    setShowForm(true);
    setFormError(null);
    setMissingDates([]);
    client.get('/api/availability/next-month-events')
      .then(r => {
        const evs = r.data.events || [];
        setNextEvents(evs);
        setSelectedEvents(evs.map(e => e.id));
      })
      .catch(() => setFormError('Не удалось загрузить события'));
  };

  const toggleShow = name => setSelectedShows(s =>
    s.includes(name) ? s.filter(x => x !== name) : [...s, name]
  );
  const toggleEvent = id => setSelectedEvents(s =>
    s.includes(id) ? s.filter(x => x !== id) : [...s, id]
  );

  const checkDates = async (ids) => {
    if (!ids.length) { setMissingDates([]); return; }
    try {
      const r = await client.get('/api/availability/check-dates', {
        params: { event_ids: ids.join(',') }
      });
      setMissingDates(r.data.missing || []);
    } catch { setMissingDates([]); }
  };

  const handleEventToggle = async (id) => {
    const next = selectedEvents.includes(id)
      ? selectedEvents.filter(x => x !== id)
      : [...selectedEvents, id];
    setSelectedEvents(next);
    await checkDates(next);
  };

  const handleSend = async () => {
    if (!selectedShows.length) { setFormError('Выберите хотя бы один спектакль'); return; }
    if (!selectedEvents.length) { setFormError('Выберите хотя бы одну дату'); return; }
    setSending(true);
    setFormError(null);
    try {
      await client.post('/api/availability/campaign', {
        show_names: selectedShows,
        event_ids: selectedEvents,
      });
      setShowForm(false);
      loadCampaign();
    } catch (e) {
      setFormError(e.response?.data?.detail || 'Ошибка отправки');
    } finally {
      setSending(false);
    }
  };

  const loadNonVoters = async () => {
    const r = await client.get('/api/availability/non-voters');
    setNonVoters(r.data.non_voters || []);
  };

  const monthLabel = (m) => {
    if (!m) return '';
    const [y, mo] = m.split('-');
    const months = ['','янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
    return `${months[parseInt(mo)]} ${y}`;
  };

  return (
    <>
      <div className="section-label" style={{ marginTop: 16 }}>Опрос занятости</div>

      {campaign === undefined ? (
        <div className="card-white" style={{ padding: '12px 16px', color: '#888', fontSize: 13 }}>Загрузка...</div>
      ) : campaign ? (
        <div className="card-white" style={{ padding: '14px 16px' }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
            Кампания на {monthLabel(campaign.month)}
          </div>
          <div style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
            {JSON.parse ? campaign.show_names?.join(', ') : ''} · {campaign.polls.reduce((s, p) => s + p.voter_count, 0)} ответов
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" style={{ fontSize: 13 }} onClick={loadNonVoters}>
              Кто не ответил
            </button>
            <button className="btn btn-secondary" style={{ fontSize: 13 }} onClick={() => { setShowForm(true); openForm(); }}>
              Новая кампания
            </button>
          </div>
          {nonVoters !== null && (
            <div style={{ marginTop: 10, fontSize: 13 }}>
              {nonVoters.length === 0
                ? <span style={{ color: '#22c55e' }}>Все ответили</span>
                : nonVoters.map(u => <span key={u} style={{ marginRight: 6 }}>@{u}</span>)
              }
            </div>
          )}
        </div>
      ) : (
        <div className="card-white" style={{ padding: '14px 16px' }}>
          <div style={{ fontSize: 13, color: '#666', marginBottom: 10 }}>Кампания ещё не запускалась</div>
          <button className="btn btn-primary" style={{ fontSize: 13 }} onClick={openForm}>
            Запустить опрос занятости
          </button>
        </div>
      )}

      {showForm && (
        <div className="card-white" style={{ padding: '14px 16px', marginTop: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 10 }}>Новая кампания</div>

          <div style={{ fontSize: 13, color: '#666', marginBottom: 6 }}>Спектакли в следующем месяце:</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
            {showNames.map(name => (
              <button
                key={name}
                onClick={() => toggleShow(name)}
                style={{
                  padding: '4px 12px', borderRadius: 16, fontSize: 13, cursor: 'pointer',
                  border: selectedShows.includes(name) ? '2px solid #5a0000' : '1.5px solid #ccc',
                  background: selectedShows.includes(name) ? '#f5e6e6' : '#fff',
                  color: '#333',
                }}
              >{name}</button>
            ))}
          </div>

          <div style={{ fontSize: 13, color: '#666', marginBottom: 6 }}>Даты (из календаря):</div>
          {nextEvents.length === 0
            ? <div style={{ fontSize: 13, color: '#aaa', marginBottom: 10 }}>Нет событий в следующем месяце</div>
            : nextEvents.map(e => (
              <label key={e.id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, fontSize: 13, cursor: 'pointer' }}>
                <input type="checkbox" checked={selectedEvents.includes(e.id)} onChange={() => handleEventToggle(e.id)} />
                {e.date_label}
              </label>
            ))
          }

          {missingDates.length > 0 && (
            <div style={{ background: '#fff8e1', border: '1px solid #f59e0b', borderRadius: 8, padding: '8px 12px', fontSize: 12, marginBottom: 10 }}>
              ⚠️ Нет столбцов в «График [составы]»: {missingDates.join(', ')}
            </div>
          )}

          {formError && <div className="alert alert-error" style={{ marginBottom: 8 }}>{formError}</div>}

          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn btn-primary" style={{ flex: 1, fontSize: 13 }} onClick={handleSend} disabled={sending}>
              {sending ? 'Отправка...' : 'Отправить в чат'}
            </button>
            <button className="btn btn-secondary" style={{ fontSize: 13 }} onClick={() => setShowForm(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </>
  );
}

export default function NotificationsView({ userId }) {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [showNames, setShowNames] = useState([]);

  useEffect(() => {
    fetch(`${API}/api/sheets/shows`)
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

      <AvailabilitySection showNames={showNames} />
    </>
  );
}
