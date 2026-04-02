import React, { useState, useEffect } from 'react';
import './index.css';
import CalendarView from './components/CalendarView';
import PollingView from './components/PollingView';
import NotificationsView from './components/NotificationsView';

function App() {
  const [activeTab, setActiveTab] = useState('calendar');
  const [userId, setUserId] = useState(null);

  useEffect(() => {
    // Получить user_id из Telegram WebApp
    if (window.Telegram?.WebApp) {
      const tg = window.Telegram.WebApp;

      // Сообщить Telegram что приложение готово
      tg.ready();

      // Развернуть приложение на весь экран
      tg.expand();

      // Получить данные пользователя
      const user = tg.initDataUnsafe?.user;
      if (user) {
        setUserId(user.id);
      }
    }
  }, []);

  return (
    <div className="container">
      <nav className="navbar">
        <button
          className={`navbar-tab ${activeTab === 'calendar' ? 'active' : ''}`}
          onClick={() => setActiveTab('calendar')}
        >
          📅 Календарь
        </button>
        <button
          className={`navbar-tab ${activeTab === 'polling' ? 'active' : ''}`}
          onClick={() => setActiveTab('polling')}
        >
          🗳️ Опросы
        </button>
        <button
          className={`navbar-tab ${activeTab === 'notifications' ? 'active' : ''}`}
          onClick={() => setActiveTab('notifications')}
        >
          🔔 Уведомления
        </button>
      </nav>

      <div className="content">
        {activeTab === 'calendar' && <CalendarView userId={userId} />}
        {activeTab === 'polling' && <PollingView userId={userId} />}
        {activeTab === 'notifications' && <NotificationsView userId={userId} />}
      </div>
    </div>
  );
}

export default App;
