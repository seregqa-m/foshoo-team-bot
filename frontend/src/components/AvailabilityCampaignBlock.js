import React, { useState } from 'react';
import client from '../api/client';
import './AvailabilityCampaignBlock.css';

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];

function PollCalendar({ month, dates }) {
  const [year, number] = month.split('-').map(Number);
  const offset = (new Date(year, number - 1, 1).getDay() + 6) % 7;
  const count = new Date(year, number, 0).getDate();
  return <div className="poll-summary-calendar" role="group" aria-label="Даты опроса">
    {WEEKDAYS.map(day => <span className="poll-summary-calendar__weekday" key={day}>{day}</span>)}
    {Array.from({ length: offset }, (_, i) => <span key={`empty-${i}`} aria-hidden="true" />)}
    {Array.from({ length: count }, (_, i) => {
      const date = `${month}-${String(i + 1).padStart(2, '0')}`;
      const selected = dates.has(date);
      return <span key={date} className={`poll-summary-calendar__day${selected ? ' poll-summary-calendar__day--selected' : ''}`}
        aria-label={`${i + 1} ${MONTHS[number - 1]} ${year}${selected ? ', дата опроса' : ''}`}>{i + 1}</span>;
    })}
  </div>;
}

function ChatPoll({ campaignId, group }) {
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const first = group.polls[0];
  const label = first.chat_title || [...group.names].join(', ') || 'Чат';
  const ping = async () => {
    if (sending) return;
    setSending(true);
    setResult(null);
    setError(null);
    try {
      const { data } = await client.post('/api/availability/ping-non-voters', null,
        { params: { campaign_id: campaignId, chat_id: group.chat } });
      if (data.errors?.length) setError(data.errors.map(item => item.error).join(' '));
      else setResult(data.count > 0 ? 'Напоминание отправлено' : 'Нет неответивших');
    } catch (e) {
      const detail = e.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Не удалось отправить напоминание');
    } finally { setSending(false); }
  };
  return <div className="poll-summary-chat">
    <div className="poll-summary-chat__row">
      {first.tg_link ? <a href={first.tg_link} target="_blank" rel="noreferrer">{label}</a> : <span>{label}</span>}
      <button className="btn btn-secondary" onClick={ping} disabled={sending || !group.chat}
        aria-label={`Пинг неответивших: ${label}`}>{sending ? 'Отправка…' : 'Пинг неответивших'}</button>
    </div>
    {error && <div className="poll-summary-chat__error" role="alert">{error}</div>}
    {result && <div className="poll-summary-chat__result" role="status">{result}</div>}
  </div>;
}

export default function AvailabilityCampaignBlock({ campaign }) {
  const polls = [...(campaign.polls || [])].sort((a, b) => a.id - b.id);
  const dates = new Set(polls.flatMap(p => (p.options || []).map(o => o.date).filter(Boolean)));
  const groups = Object.values(polls.filter(p => p.telegram_message_id).reduce((result, poll) => {
    const key = poll.telegram_chat_id ?? 'legacy';
    if (!result[key]) result[key] = { chat: poll.telegram_chat_id, names: new Set(), polls: [] };
    (poll.show_names || campaign.show_names || []).forEach(name => result[key].names.add(name));
    result[key].polls.push(poll);
    return result;
  }, {}));
  const [year, number] = campaign.month.split('-').map(Number);
  const created = campaign.created_at && new Date(/Z$|[+-]\d\d:\d\d$/.test(campaign.created_at)
    ? campaign.created_at : `${campaign.created_at}Z`).toLocaleDateString('ru-RU', {
    day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/Moscow',
  }).replace(/ г\.$/, '');
  const title = `Опрос на ${MONTHS[number - 1]} ${year}${created ? ` от ${created}` : ''}`;
  return <article className="card-white poll-summary" aria-label={title}>
    <h3 className="poll-summary__title">{title}</h3>
    <PollCalendar month={campaign.month} dates={dates} />
    {groups.map(group => <ChatPoll key={group.chat ?? 'legacy'} campaignId={campaign.id} group={group} />)}
  </article>;
}
