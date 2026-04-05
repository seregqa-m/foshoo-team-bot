import React, { useState, useEffect } from 'react';
import './index.css';
import CalendarView from './components/CalendarView';
import PollingView from './components/PollingView';
import NotificationsView from './components/NotificationsView';
import FinanceView from './components/FinanceView';
import LinksView from './components/LinksView';

function App() {
  const [activeTab, setActiveTab] = useState('calendar');
  const [userId, setUserId] = useState(null);
  const [username, setUsername] = useState('');
  const [allowed, setAllowed] = useState(null); // null = проверяем
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    if (window.Telegram?.WebApp) {
      const tg = window.Telegram.WebApp;
      tg.ready();
      tg.expand();
      const user = tg.initDataUnsafe?.user;
      if (user) {
        setUserId(user.id);
        const username = user.username || '';
        setUsername(username);
        fetch(`${process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000'}/api/auth/check?username=${username}&user_id=${user.id}`)
          .then(r => r.json())
          .then(data => { setAllowed(data.allowed); setIsAdmin(!!data.is_admin); })
          .catch(() => setAllowed(true)); // при ошибке — пускаем
      } else {
        setAllowed(false);
      }
    } else {
      setAllowed(true); // вне Telegram (дев) — пускаем
    }
  }, []);

  if (allowed === null) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: 'sans-serif' }}>Загрузка...</div>;
  }

  if (!allowed) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: 'sans-serif', textAlign: 'center', padding: '0 32px' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>🎭</div>
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>Доступ закрыт</div>
        <div style={{ fontSize: 14, color: '#666' }}>Это приложение только для участников студии</div>
      </div>
    );
  }

  return (
    <div className="app">
      <main className="content">
        {activeTab === 'calendar' && <CalendarView userId={userId} isAdmin={isAdmin} />}
        {activeTab === 'polling' && <PollingView userId={userId} />}
        {activeTab === 'finance' && <FinanceView username={username} />}
        {activeTab === 'links' && <LinksView />}
        {activeTab === 'notifications' && <NotificationsView userId={userId} />}
      </main>

      <nav className="tab-bar">
        <button
          className={activeTab === 'calendar' ? 'active' : ''}
          onClick={() => setActiveTab('calendar')}
        >
          📅<span>Расписание</span>
        </button>
        <button
          className={activeTab === 'polling' ? 'active' : ''}
          onClick={() => setActiveTab('polling')}
        >
          🗳️<span>Опросы</span>
        </button>
        <button
          className={activeTab === 'finance' ? 'active' : ''}
          onClick={() => setActiveTab('finance')}
        >
          💰<span>Финансы</span>
        </button>
        <button
          className={activeTab === 'links' ? 'active' : ''}
          onClick={() => setActiveTab('links')}
        >
          🗂️<span>Ресурсы</span>
        </button>
        <button
          className={activeTab === 'notifications' ? 'active' : ''}
          onClick={() => setActiveTab('notifications')}
        >
          🔔<span>Уведомления</span>
        </button>
      </nav>
    </div>
  );
}

export default App;
