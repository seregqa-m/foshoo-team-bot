import React, { useState } from 'react';
import client from '../api/client';

const formatDates = dates => dates.map(day => day.split('-').reverse().join('.')).join(', ');
const rosterExplanation = reason => ({
  ambiguous_identity: 'Не удалось однозначно определить Telegram-аккаунт. Проверьте Telegram ID и username в таблице «Труппа».',
  not_registered: 'Бот ещё не связал участника с Telegram-аккаунтом. Попросите его ответить в опросе бота в любой подключённой группе; если он уже голосовал — проверьте Telegram ID и username в таблице «Труппа».',
  membership_unverified: 'Бот знает участника, но пока не подтвердил членство в группе этого спектакля. Проверка выполняется автоматически; повторное голосование для регистрации не нужно.',
  not_member: 'По последней проверке Telegram участник не состоит в группе этого спектакля. Ответы из других групп учитываются; пинг в эту группу не отправляется.',
}[reason] || 'Не удалось проверить участника. Обновите список.');

export default function AvailabilityCampaignBlock({ campaign }) {
  const [nonVoters, setNonVoters] = useState(null);
  const [unregistered, setUnregistered] = useState([]);
  const [rosterWarning, setRosterWarning] = useState(null);
  const [pinging, setPinging] = useState(false);
  const [loadingNonVoters, setLoadingNonVoters] = useState(false);
  const [formError, setFormError] = useState(null);

  const loadNonVoters = async () => {
    setLoadingNonVoters(true);
    setFormError(null);
    try {
      const r = await client.get('/api/availability/non-voters', { params: { campaign_id: campaign.id } });
      setNonVoters(r.data.participants || (r.data.non_voters || []).map(username => ({ user_id: username, username })));
      setUnregistered(r.data.unregistered_participants || []);
      setRosterWarning(r.data.roster_warning || null);
    } catch (e) { setFormError(e.response?.data?.detail || 'Не удалось загрузить неответивших'); }
    finally { setLoadingNonVoters(false); }
  };

  const handlePing = async () => {
    setPinging(true);
    try {
      const { data } = await client.post('/api/availability/ping-non-voters', null, { params: { campaign_id: campaign.id } });
      await loadNonVoters();
      if (data.errors?.length) setFormError(data.errors.map(e => `Чат ${e.chat_id}: ${e.error}`).join(' '));
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

  const polls = campaign.polls || [];
  const dates = [...new Set(polls.flatMap(p => (p.options || []).map(o => o.date).filter(Boolean)))].sort();
  const groups = Object.values(polls.reduce((result, poll) => {
    const key = poll.telegram_chat_id ?? 'legacy';
    if (!result[key]) result[key] = { chat: key, names: new Set(), polls: [] };
    (poll.show_names || campaign.show_names || []).forEach(name => result[key].names.add(name));
    result[key].polls.push(poll);
    return result;
  }, {}));
  const sent = polls.filter(p => p.telegram_message_id).length;
  const createdAt = campaign.created_at && new Date(/Z$|[+-]\d\d:\d\d$/.test(campaign.created_at)
    ? campaign.created_at : `${campaign.created_at}Z`).toLocaleString('ru-RU', {
    day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
  });

  return (
    <article aria-label={`Блок опроса №${campaign.id}`} style={{ marginBottom: 10 }}>
        <div className="card-white" style={{ padding: '14px 16px' }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
            {monthLabel(campaign.month)} · Блок №{campaign.id}
          </div>
          {createdAt && <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>Создан {createdAt}</div>}
          <div style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
            {campaign.show_names?.join(', ')}
          </div>
          <div style={{ fontSize: 13, marginBottom: 8 }}>
            {dates.length > 0 ? <>Даты ({dates.length}): {formatDates(dates)}</> : 'Даты указаны в исходных опросах'}
          </div>
          <details style={{ fontSize: 12, marginBottom: 12 }}>
            <summary style={{ cursor: 'pointer' }}>Опросы в группах ({groups.length}) · отправлено {sent} из {polls.length}</summary>
            {groups.map(group => <div key={group.chat} style={{ marginTop: 10 }}>
              <strong>{[...group.names].join(', ') || 'Группа'}</strong>
              {group.polls.map((poll, index) => <div key={poll.id} style={{ marginTop: 5 }}>
                Часть {index + 1} из {group.polls.length} · {poll.telegram_message_id
                  ? (poll.tg_link ? <a href={poll.tg_link} target="_blank" rel="noreferrer">Открыть опрос</a> : 'Отправлен')
                  : ['sending', 'uncertain'].includes(poll.delivery_state) ? 'Отправка не подтверждена' : 'Не отправлен'}
                <div style={{ color: '#666' }}>{(poll.options || []).map(o => o.date_label || o.date).filter(Boolean).join(', ')}</div>
              </div>)}
            </div>)}
          </details>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" style={{ fontSize: 13 }} onClick={loadNonVoters} disabled={loadingNonVoters || pinging}>
              {loadingNonVoters ? 'Проверяем участников…' : 'Посмотреть неответивших'}
            </button>
          </div>
          {nonVoters !== null && (
            <div style={{ marginTop: 10 }}>
              <p style={{ fontSize: 13 }}>Занятость общая на каждую дату: учитываются ответы из всех групп и из приложения. Повторно отвечать на ту же дату не нужно.</p>
              {rosterWarning && <div className="alert alert-error" role="alert">{rosterWarning}</div>}
              {nonVoters.length === 0
                ? <span style={{ fontSize: 13, color: '#22c55e' }}>Среди зарегистрированных участников нет ожидающих ответа</span>
                : <>
                    <div style={{ fontSize: 13, marginBottom: 8 }}>
                      {nonVoters.map(u => <div key={u.user_id}>{u.username ? `@${u.username}` : u.name}
                        {u.missing_dates?.length > 0 && <> — нет ответа на: {formatDates(u.missing_dates)}</>}
                      </div>)}
                    </div>
                    <button className="btn btn-primary" style={{ fontSize: 13 }} onClick={handlePing} disabled={pinging || loadingNonVoters}>
                      {pinging ? 'Отправка...' : 'Пингануть'}
                    </button>
                  </>
              }
              {unregistered.length > 0 && <div style={{ marginTop: 12, fontSize: 13 }}>
                <strong>Участники составов, которым нельзя отправить пинг</strong>
                <ul style={{ paddingLeft: 20, margin: '8px 0' }}>{unregistered.map(u => <li key={`${u.name}:${u.username}:${u.chat_id}`}>
                  {u.name}{u.username ? ` (@${u.username})` : ''} — {u.show_names.join(', ')}.
                  {' '}{rosterExplanation(u.reason)}
                  <div>{u.missing_dates != null
                    ? <>Ответы есть на {u.answered_count} из {u.total_dates} дат. Нет ответа на: {formatDates(u.missing_dates)}.</>
                    : 'Наличие ответов пока нельзя проверить: Telegram-аккаунт не определён.'}</div>
                </li>)}</ul>
                <p>Эти участники не включены в пинг. Для пинга нужны известный Telegram-аккаунт, подтверждённое членство в группе и хотя бы одна дата без ответа.</p>
              </div>}
            </div>
          )}
        </div>
      {formError && <div className="alert alert-error" role="alert">{formError}</div>}
    </article>
  );
}
