import React, { useState, useEffect } from 'react';
import './index.css';
import CalendarView from './components/CalendarView';
import PollingView from './components/PollingView';
import NotificationsView from './components/NotificationsView';

function App() {
  const [activeTab, setActiveTab] = useState('calendar');
  const [userId, setUserId] = useState(null);

  useEffect(() => {
    if (window.Telegram?.WebApp) {
      const tg = window.Telegram.WebApp;
      tg.ready();
      tg.expand();
      const user = tg.initDataUnsafe?.user;
      if (user) setUserId(user.id);
    }
  }, []);

  return (
    <div className="app">
      <main className="content">
        {activeTab === 'calendar' && <CalendarView userId={userId} />}
        {activeTab === 'polling' && <PollingView userId={userId} />}
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
