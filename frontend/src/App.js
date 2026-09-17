import React, { useState, useEffect } from 'react';
import './index.css';
import client, { DATA_CHANGED_EVENT } from './api/client';
import AssistantView from './components/AssistantView';
import CalendarView from './components/CalendarView';
import NotificationsView from './components/NotificationsView';
import FinanceView from './components/FinanceView';
import LinksView from './components/LinksView';

function App() {
  const [activeTab, setActiveTab] = useState('assistant');
  const [visitedTabs, setVisitedTabs] = useState(['assistant']);
  const [dataVersion, setDataVersion] = useState(0);
  const selectTab = tab => {
    setVisitedTabs(tabs => tabs.includes(tab) ? tabs : [...tabs, tab]);
    setActiveTab(tab);
  };
  useEffect(() => {
    const refresh = () => setDataVersion(version => version + 1);
    window.addEventListener(DATA_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(DATA_CHANGED_EVENT, refresh);
  }, []);
  const [userId, setUserId] = useState(null);
  const [username, setUsername] = useState('');
  const [allowed, setAllowed] = useState(null); // null = проверяем
  const [isAdmin, setIsAdmin] = useState(false);
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [trouFilter, setTrouFilter] = useState('труппа 1');

  const [accessError, setAccessError] = useState('');

  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();
    client.get('/api/auth/check')
      .then(({ data }) => {
        setUserId(data.user_id);
        setUsername(data.username);
        setIsAdmin(data.is_admin);
        setIsSuperAdmin(!!data.is_superadmin);
        setAllowed(data.allowed);
        return client.get('/api/auth/app-config');
      })
      .then(({ data }) => { if (data.troupe_filter) setTrouFilter(data.troupe_filter); })
      .catch(e => {
        setAccessError(e.response?.data?.detail || 'Не удалось проверить доступ. Попробуй открыть приложение заново.');
        setAllowed(false);
      });
  }, []);

  useEffect(() => {
    if (!allowed || !dataVersion) return;
    let active = true;
    Promise.all([client.get('/api/auth/check'), client.get('/api/auth/app-config')])
      .then(([auth, config]) => {
        if (!active) return;
        setIsAdmin(auth.data.is_admin); setIsSuperAdmin(!!auth.data.is_superadmin);
        setTrouFilter(config.data.troupe_filter);
      })
      .catch(e => {
        if (!active) return;
        setIsAdmin(false); setIsSuperAdmin(false);
        if ([401, 403].includes(e.response?.status)) { setAccessError(e.response.data.detail); setAllowed(false); }
      });
    return () => { active = false; };
  }, [allowed, dataVersion]);

  if (allowed === null) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: 'sans-serif' }}>Загрузка...</div>;
  }

  if (!allowed) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: 'sans-serif', textAlign: 'center', padding: '0 32px' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>🎭</div>
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 12 }}>Театр-студия FoShoo</div>
        <div style={{ fontSize: 14, color: '#444', marginBottom: 20, lineHeight: 1.5 }}>
          {accessError || 'Это приложение театра-студии FoShoo.'}
        </div>
        <a href="https://foshoo-theatre.ru/" target="_blank" rel="noopener noreferrer"
           style={{ fontSize: 15, color: '#5a0000', fontWeight: 600, textDecoration: 'none', borderBottom: '1px solid #5a0000' }}>
          foshoo-theatre.ru
        </a>
      </div>
    );
  }

  return (
    <div className="app">
      <main className={`content ${activeTab === 'assistant' ? 'content--assistant' : ''}`}>
        <section hidden={activeTab !== 'assistant'}>
          <AssistantView
            active={activeTab === 'assistant'}
            userId={userId}
            username={username}
            renderSettings={() => isAdmin ? <NotificationsView userId={userId} isSuperAdmin={isSuperAdmin} /> : <p>Настройки доступны администратору.</p>}
          />
        </section>
        {visitedTabs.includes('calendar') && <section hidden={activeTab !== 'calendar'}>
          <CalendarView active={activeTab === 'calendar'} dataVersion={dataVersion} userId={userId} isAdmin={isAdmin} trouFilter={trouFilter} />
        </section>}
        {visitedTabs.includes('finance') && <section hidden={activeTab !== 'finance'}>
          <FinanceView active={activeTab === 'finance'} dataVersion={dataVersion} username={username} isAdmin={isAdmin} />
        </section>}
        {visitedTabs.includes('links') && <section hidden={activeTab !== 'links'}>
          <LinksView isAdmin={isAdmin} />
        </section>}
      </main>

      <nav className="tab-bar">
        <button
          className={activeTab === 'assistant' ? 'active' : ''}
          onClick={() => selectTab('assistant')}
        >
          🤖<span>Ассистент</span>
        </button>
        <button
          className={activeTab === 'calendar' ? 'active' : ''}
          onClick={() => selectTab('calendar')}
        >
          📅<span>Расписание</span>
        </button>
        <button
          className={activeTab === 'finance' ? 'active' : ''}
          onClick={() => selectTab('finance')}
        >
          💰<span>Финансы</span>
        </button>
        <button
          className={activeTab === 'links' ? 'active' : ''}
          onClick={() => selectTab('links')}
        >
          🗂️<span>Ресурсы</span>
        </button>
      </nav>
    </div>
  );
}

export default App;
