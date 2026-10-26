import React, { useState, useEffect } from 'react';
import client from '../api/client';
import AvailabilityCalendar from './AvailabilityCalendar';

export default function AvailabilitySection({ showNames }) {
  const [campaign, setCampaign] = useState(undefined); // undefined=loading, null=none
  const [showForm, setShowForm] = useState(false);
  const [month, setMonth] = useState(null);
  const [requestedMonth, setRequestedMonth] = useState(null);
  const [suggestedDates, setSuggestedDates] = useState([]);
  const [datesLoading, setDatesLoading] = useState(true);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [selectedShows, setSelectedShows] = useState([]);
  const [selectedDates, setSelectedDates] = useState([]);
  const [missingDates, setMissingDates] = useState([]);
  const [nonVoters, setNonVoters] = useState(null);
  const [unregistered, setUnregistered] = useState([]);
  const [rosterWarning, setRosterWarning] = useState(null);
  const [pinging, setPinging] = useState(false);
  const [sending, setSending] = useState(false);
  const [formError, setFormError] = useState(null);
  const [unconfirmed, setUnconfirmed] = useState(false);

  const loadCampaign = campaignId => {
    client.get('/api/availability/current', campaignId ? { params: { campaign_id: campaignId } } : undefined)
      .then(r => setCampaign(r.data.campaign || null))
      .catch(() => { setCampaign(null); setFormError('Не удалось загрузить опрос занятости'); });
  };

  useEffect(() => { loadCampaign(); }, []);

  const openForm = () => {
    setFormError(null);
    setRequestedMonth(null);
    setUnconfirmed(false);
    setShowForm(true);
  };

  useEffect(() => {
    if (!showForm) return;
    let active = true;
    setDatesLoading(true);
    setMonth(null);
    setSelectedDates([]);
    setSuggestedDates([]);
    setMissingDates([]);
    setFormError(null);
    client.get('/api/availability/next-month-events', requestedMonth ? { params: { month: requestedMonth } } : undefined)
      .then(({ data }) => {
        if (!active) return;
        const dates = [...new Set((data.events || []).map(e => e.start_time.slice(0, 10)))].sort();
        setMonth(data.month);
        setSuggestedDates(dates);
        setSelectedDates(dates);
      })
      .catch(() => { if (active) setFormError('Не удалось загрузить даты из расписания'); })
      .finally(() => { if (active) setDatesLoading(false); });
    return () => { active = false; };
  }, [showForm, loadAttempt, requestedMonth]);

  const changeMonth = value => {
    if (!/^\d{4}-\d{2}$/.test(value) || value === (requestedMonth || month)) return;
    setDatesLoading(true);
    setSelectedDates([]);
    setRequestedMonth(value);
  };
  const shiftMonth = offset => {
    const [year, number] = (requestedMonth || month).split('-').map(Number);
    const next = new Date(year, number - 1 + offset, 1);
    changeMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`);
  };

  useEffect(() => {
    setMissingDates([]);
    if (!showForm || !selectedDates.length) return;
    let active = true;
    const timer = setTimeout(() => {
      client.get('/api/availability/check-dates', { params: { dates: selectedDates.join(',') } })
        .then(({ data }) => { if (active) setMissingDates(data.missing || []); })
        .catch(() => {});
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [showForm, selectedDates]);

  const toggleShow = name => setSelectedShows(s =>
    s.includes(name) ? s.filter(x => x !== name) : [...s, name]
  );
  const toggleDate = date => {
    setSelectedDates(dates => dates.includes(date)
      ? dates.filter(value => value !== date)
      : [...dates, date].sort());
    setFormError(null);
  };

  const handleSend = async () => {
    if (sending || datesLoading || !month) return;
    if (!selectedShows.length) { setFormError('Выберите хотя бы один спектакль'); return; }
    if (!selectedDates.length) { setFormError('Выберите хотя бы одну дату'); return; }
    if (unconfirmed && !window.confirm('Telegram не подтвердил отправку. Проверьте указанные чаты: если опрос уже появился, повторять не нужно. Подтверждаете, что его нет, и повторить отправку?')) return;
    setSending(true);
    setFormError(null);
    try {
      const { data } = await client.post('/api/availability/campaign', {
        show_names: selectedShows,
        dates: selectedDates,
        ...(unconfirmed ? { retry_unconfirmed: true } : {}),
      });
      if (data.errors?.length) {
        setUnconfirmed(data.errors.some(e => ['uncertain', 'sending'].includes(e.delivery_state)));
        setFormError(data.errors.map(e => `Чат ${e.chat_id}: ${e.error}`).join(' '));
      } else {
        setUnconfirmed(false);
        setShowForm(false);
      }
      setNonVoters(null);
      setUnregistered([]);
      setRosterWarning(null);
      loadCampaign(data.campaign_id);
    } catch (e) {
      setFormError(e.response?.data?.detail || 'Ошибка отправки');
    } finally {
      setSending(false);
    }
  };

  const loadNonVoters = async () => {
    try {
      const r = await client.get('/api/availability/non-voters', { params: { campaign_id: campaign.id } });
      setNonVoters(r.data.participants || (r.data.non_voters || []).map(username => ({ user_id: username, username })));
      setUnregistered(r.data.unregistered_participants || []);
      setRosterWarning(r.data.roster_warning || null);
    } catch (e) { setFormError(e.response?.data?.detail || 'Не удалось загрузить неответивших'); }
  };

  const handlePing = async () => {
    setPinging(true);
    try {
      const { data } = await client.post('/api/availability/ping-non-voters', null, { params: { campaign_id: campaign.id } });
      setFormError(data.errors?.length ? data.errors.map(e => `Чат ${e.chat_id}: ${e.error}`).join(' ') : null);
    } catch (e) {
      setFormError(e.response?.data?.detail || 'Не удалось отправить напоминание');
    } finally {
      setPinging(false);
    }
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
            Опрос на {monthLabel(campaign.month)}
          </div>
          <div style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
            {campaign.show_names?.join(', ')}
          </div>
          {campaign.polls.map(p => <div key={p.id} style={{ fontSize: 12, marginBottom: 6 }}>
            {p.show_names?.join(', ')} · {p.telegram_message_id ? (p.tg_link ? <a href={p.tg_link} target="_blank" rel="noreferrer">Открыть опрос</a> : 'Отправлен') : 'Не отправлен'}
          </div>)}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" style={{ fontSize: 13 }} onClick={loadNonVoters}>
              Посмотреть неответивших
            </button>
            <button className="btn btn-secondary" style={{ fontSize: 13 }} onClick={openForm}>
              Новый опрос
            </button>
          </div>
          {nonVoters !== null && (
            <div style={{ marginTop: 10 }}>
              {rosterWarning && <div className="alert alert-error" role="alert">{rosterWarning}</div>}
              {nonVoters.length === 0
                ? <span style={{ fontSize: 13, color: '#22c55e' }}>Среди зарегистрированных участников нет ожидающих ответа</span>
                : <>
                    <div style={{ fontSize: 13, marginBottom: 8 }}>
                      {nonVoters.map(u => <span key={u.user_id} style={{ marginRight: 6 }}>{u.username ? `@${u.username}` : u.name}</span>)}
                    </div>
                    <button className="btn btn-primary" style={{ fontSize: 13 }} onClick={handlePing} disabled={pinging}>
                      {pinging ? 'Отправка...' : 'Пингануть'}
                    </button>
                  </>
              }
              {unregistered.length > 0 && <div style={{ marginTop: 12, fontSize: 13 }}>
                <strong>Участники составов без подтверждённой регистрации</strong>
                <ul style={{ paddingLeft: 20, margin: '8px 0' }}>{unregistered.map(u => <li key={`${u.name}:${u.username}`}>
                  {u.name}{u.username ? ` (@${u.username})` : ''} — {u.show_names.join(', ')}.
                  {' '}{u.reason === 'ambiguous_identity' ? 'Нужно проверить привязку в таблице.'
                    : u.reason === 'membership_unverified' ? 'Членство в группе не подтверждено.' : 'Бот ещё не зарегистрировал участника.'}
                </li>)}</ul>
                <p>Эти участники не включены в пинг: их ответы пока нельзя надёжно сопоставить.
                  {' '}Попросите их проголосовать в опросе — бот получит Telegram ID и проверит членство в группе.</p>
              </div>}
            </div>
          )}
        </div>
      ) : (
        <div className="card-white" style={{ padding: '14px 16px' }}>
          <div style={{ fontSize: 13, color: '#666', marginBottom: 10 }}>Опрос ещё не запускался</div>
          <button className="btn btn-primary" style={{ fontSize: 13 }} onClick={openForm}>
            Запустить опрос занятости
          </button>
        </div>
      )}

      {!showForm && formError && <div className="alert alert-error">{formError}</div>}
      {showForm && (
        <div className="card-white" style={{ padding: '14px 16px', marginTop: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 10 }}>Новый опрос</div>
          <p style={{ fontSize: 13 }}>Ответы общие на каждую дату для всех спектаклей. Чаты задаются в «Спектакли и чаты». Повторная отправка тех же дат в те же чаты не создаёт копии.</p>

          <div style={{ fontSize: 13, color: '#666', marginBottom: 6 }}>В чаты каких спектаклей отправить опрос:</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
            {showNames.map(name => (
              <button
                key={name}
                onClick={() => toggleShow(name)}
                disabled={sending}
                style={{
                  padding: '4px 12px', borderRadius: 16, fontSize: 13, cursor: 'pointer',
                  border: selectedShows.includes(name) ? '2px solid #5a0000' : '1.5px solid #ccc',
                  background: selectedShows.includes(name) ? '#f5e6e6' : '#fff',
                  color: '#333',
                }}
              >{name}</button>
            ))}
          </div>

          <label className="availability-calendar__month-label" htmlFor="availability-month">Месяц опроса</label>
          <div className="availability-calendar__navigation">
            <button type="button" className="btn btn-secondary" aria-label="Предыдущий месяц" disabled={sending || !(requestedMonth || month)} onClick={() => shiftMonth(-1)}>‹</button>
            <input id="availability-month" type="month" className="form-input" value={requestedMonth || month || ''} disabled={sending} onChange={e => changeMonth(e.target.value)} />
            <button type="button" className="btn btn-secondary" aria-label="Следующий месяц" disabled={sending || !(requestedMonth || month)} onClick={() => shiftMonth(1)}>›</button>
          </div>
          <p className="availability-calendar__hint">При смене месяца даты выбираются заново из расписания.</p>

          {datesLoading ? <div role="status">Загружаем даты из расписания...</div> : month ? (
            <AvailabilityCalendar
              month={month} selectedDates={selectedDates} suggestedDates={suggestedDates}
              onToggle={toggleDate} disabled={sending}
            />
          ) : (
            <button className="btn btn-secondary" onClick={() => setLoadAttempt(n => n + 1)}>Повторить загрузку</button>
          )}

          {missingDates.length > 0 && (
            <div style={{ background: '#fff8e1', border: '1px solid #f59e0b', borderRadius: 8, padding: '8px 12px', fontSize: 12, marginBottom: 10 }}>
              В «График [составы]» будут добавлены даты: {missingDates.join(', ')}
            </div>
          )}

          {formError && <div className="alert alert-error" style={{ marginBottom: 8 }}>{formError}</div>}

          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn btn-primary" style={{ flex: 1, fontSize: 13 }} onClick={handleSend} disabled={sending || datesLoading || !month || !selectedDates.length}>
              {sending ? 'Отправка...' : 'Отправить в чаты'}
            </button>
            <button className="btn btn-secondary" style={{ fontSize: 13 }} onClick={() => setShowForm(false)} disabled={sending}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </>
  );
}
