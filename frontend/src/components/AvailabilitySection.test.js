import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import AvailabilitySection from './AvailabilitySection';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
let root, container, events;
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);
const day = n => container.querySelectorAll('.availability-calendar__day')[n - 1];
const open = async () => {
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => button('Запустить опрос занятости').click());
};
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  events = [
    { id: 1, start_time: '2026-10-03T00:30:00+03:00' },
    { id: 2, start_time: '2026-10-03T19:00:00+03:00' },
    { id: 3, start_time: '2026-10-10T19:00:00+03:00' },
  ];
  client.get.mockImplementation(url => Promise.resolve({ data: {
    '/api/availability/campaigns': { campaigns: [] },
    '/api/availability/next-month-events': { month: '2026-10', events },
    '/api/availability/check-dates': { missing: [] },
  }[url] }));
  client.post.mockResolvedValue({ data: {} });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test('shows unregistered cast members even when registered participants all answered, without offering to ping them', async () => {
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/campaigns')
    ? { campaigns: [{ id: 2, month: '2026-12', show_names: ['Урод'], polls: [] }] }
    : { participants: [], unregistered_participants: [{ name: 'Никита Мягков', username: 'q_poo', show_names: ['Урод', 'Любовь Громова'], reason: 'not_registered', can_ping: false }] } }));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => button('Посмотреть неответивших').click());
  expect(container.textContent).toContain('Никита Мягков (@q_poo)');
  expect(container.textContent).toContain('Урод, Любовь Громова');
  expect(container.textContent).toContain('не включены в пинг');
  expect(button('Пингануть')).toBeUndefined();
  expect(client.post).not.toHaveBeenCalled();
});

test('shows a roster warning when cast verification is unavailable', async () => {
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/campaigns')
    ? { campaigns: [{ id: 2, month: '2026-12', polls: [] }] }
    : { participants: [], roster_warning: 'Не удалось сверить составы.' } }));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => button('Посмотреть неответивших').click());
  expect(container.querySelector('[role="alert"]').textContent).toContain('Не удалось сверить составы');
});

test('separates known identity, missing membership and missing dates without asking to vote again', async () => {
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/campaigns')
    ? { campaigns: [{ id: 2, month: '2026-12', polls: [] }] }
    : { participants: [], unregistered_participants: [{ name: 'Дарья', username: 'darya',
      show_names: ['Любовь Громова'], chat_id: -1001, reason: 'membership_unverified',
      missing_dates: ['2026-12-24'], answered_count: 2, total_dates: 3 }] } }));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => button('Посмотреть неответивших').click());
  expect(container.textContent).toContain('Бот знает участника');
  expect(container.textContent).toContain('Ответы есть на 2 из 3 дат');
  expect(container.textContent).toContain('Нет ответа на: 24.12.2026');
  expect(container.textContent).toContain('учитываются ответы из всех групп и из приложения');
  expect(container.textContent).not.toContain('Попросите его ответить');
  expect(container.textContent).not.toContain('их ответы пока нельзя надёжно сопоставить');
  expect(button('Пингануть')).toBeUndefined();
});

test('shows confirmed absence separately from an ambiguous account', async () => {
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/campaigns')
    ? { campaigns: [{ id: 2, month: '2026-12', polls: [] }] }
    : { participants: [], unregistered_participants: [
      { name: 'Дарья', show_names: ['Любовь Громова'], reason: 'not_member',
        missing_dates: ['2026-12-24'], answered_count: 0, total_dates: 1 },
      { name: 'Анна', show_names: ['Урод'], reason: 'ambiguous_identity', missing_dates: null },
    ] } }));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => button('Посмотреть неответивших').click());
  expect(container.textContent).toContain('не состоит в группе этого спектакля');
  expect(container.textContent).toContain('Проверьте Telegram ID и username');
  expect(container.textContent).toContain('Наличие ответов пока нельзя проверить');
});

test('lists missing dates for ping recipients and refreshes after pinging', async () => {
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/campaigns')
    ? { campaigns: [{ id: 2, month: '2026-12', polls: [] }] }
    : { participants: [{ user_id: 42, name: 'Дарья', missing_dates: ['2026-12-24'] }] } }));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => button('Посмотреть неответивших').click());
  expect(container.textContent).toContain('Дарья — нет ответа на: 24.12.2026');
  await act(async () => button('Пингануть').click());
  expect(client.post).toHaveBeenCalledWith('/api/availability/ping-non-voters', null, { params: { campaign_id: 2 } });
  expect(client.get.mock.calls.filter(([url]) => url.endsWith('/non-voters'))).toHaveLength(2);
});

const savedBlock = (id, dates = ['2026-12-23']) => ({
  id, month: '2026-12', created_at: '2026-11-23T12:00:00', show_names: ['Урод', 'Любовь Громова'],
  polls: [-1001, -1002].flatMap((chat, group) => [0, 1].map(part => ({
    id: id * 10 + group * 2 + part, telegram_chat_id: chat, telegram_message_id: part + 1,
    show_names: [group ? 'Любовь Громова' : 'Урод'], tg_link: `https://t.me/c/${-chat}/${part + 1}`,
    options: dates.map(date => ({ date, date_label: date })),
  }))),
});
const blockNode = id => container.querySelector(`[aria-label="Блок опроса №${id}"]`);
const blockButton = (id, text) => [...blockNode(id).querySelectorAll('button')].find(b => b.textContent === text);

test('renders saved sends as blocks with collapsed chat copies and independent ping targets', async () => {
  client.get.mockImplementation((url, config) => Promise.resolve({ data: url.endsWith('/campaigns')
    ? { campaigns: [savedBlock(2, ['2026-12-24']), savedBlock(1)] }
    : { participants: [{ user_id: 42, name: `Участник блока ${config.params.campaign_id}`, missing_dates: ['2026-12-23'] }] } }));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  expect(container.querySelectorAll('article')).toHaveLength(2);
  expect(blockNode(1).textContent).toContain('Даты (1): 23.12.2026');
  expect(blockNode(1).querySelector('details').open).toBe(false);
  expect(blockNode(1).querySelectorAll('a')).toHaveLength(4);
  expect(blockNode(1).textContent).toContain('Часть 2 из 2');
  await act(async () => blockButton(1, 'Посмотреть неответивших').click());
  expect(blockNode(1).textContent).toContain('Участник блока 1');
  expect(blockNode(2).textContent).not.toContain('Участник блока 1');
  await act(async () => blockButton(1, 'Пингануть').click());
  expect(client.post).toHaveBeenLastCalledWith('/api/availability/ping-non-voters', null, { params: { campaign_id: 1 } });
});

test('new sends append a block and retain older blocks after reloading the screen', async () => {
  const original = client.get.getMockImplementation();
  let saved = [savedBlock(1)];
  client.get.mockImplementation((url, config) => url.endsWith('/campaigns')
    ? Promise.resolve({ data: { campaigns: saved } }) : original(url, config));
  client.post.mockImplementation(() => {
    saved = [savedBlock(2, ['2026-12-24']), ...saved];
    return Promise.resolve({ data: { campaign_id: 2 } });
  });
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => button('Новый опрос').click());
  await act(async () => button('Урод').click());
  await act(async () => button('Отправить в чаты').click());
  expect(container.querySelectorAll('article')).toHaveLength(2);
  expect(blockNode(1)).toBeTruthy();
  await act(async () => root.render(null));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  expect(container.querySelectorAll('article')).toHaveLength(2);
});

test('concurrent block lookups keep late answers in their own block', async () => {
  const pending = {};
  client.get.mockImplementation((url, config) => url.endsWith('/campaigns')
    ? Promise.resolve({ data: { campaigns: [savedBlock(2), savedBlock(1)] } })
    : new Promise(resolve => { pending[config.params.campaign_id] = resolve; }));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => blockButton(1, 'Посмотреть неответивших').click());
  await act(async () => blockButton(2, 'Посмотреть неответивших').click());
  await act(async () => pending[2]({ data: { participants: [{ user_id: 42, name: 'Второй' }] } }));
  await act(async () => pending[1]({ data: { participants: [{ user_id: 43, name: 'Первый' }] } }));
  expect(blockNode(1).textContent).toContain('Первый');
  expect(blockNode(1).textContent).not.toContain('Второй');
  expect(blockNode(2).textContent).toContain('Второй');
});

test('legacy blocks show original Telegram links and can ping without being sent again', async () => {
  const legacy = { id: 1, month: '2026-09', created_at: '2026-08-25T12:00:00', show_names: ['Урод'], polls: [{
    id: 10, telegram_chat_id: -100123456, telegram_message_id: 89,
    tg_link: 'https://t.me/c/123456/89', delivery_state: null, show_names: null,
    options: [{ date: '2026-09-03', date_label: '3 сентября' }],
  }] };
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/campaigns')
    ? { campaigns: [savedBlock(2), legacy] }
    : { participants: [{ user_id: 42, name: 'Анна', missing_dates: ['2026-09-03'] }] } }));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  expect(blockNode(1).querySelector('a').href).toBe('https://t.me/c/123456/89');
  expect(blockNode(1).textContent).toContain('сен 2026');
  expect(blockNode(1).textContent).toContain('отправлено 1 из 1');
  await act(async () => blockButton(1, 'Посмотреть неответивших').click());
  await act(async () => blockButton(1, 'Пингануть').click());
  expect(client.post).toHaveBeenCalledTimes(1);
  expect(client.post).toHaveBeenCalledWith('/api/availability/ping-non-voters', null, { params: { campaign_id: 1 } });
});

test('preselects unique calendar dates and sends only the final selected dates', async () => {
  await open();
  expect(container.querySelectorAll('.availability-calendar__day')).toHaveLength(31);
  expect(day(3).getAttribute('aria-pressed')).toBe('true');
  expect(day(10).getAttribute('aria-pressed')).toBe('true');
  expect(container.textContent).toContain('Выбрано дат: 2');
  await act(async () => { day(3).click(); day(7).click(); button('Урод').click(); });
  expect(day(3).getAttribute('aria-pressed')).toBe('false');
  expect(day(7).getAttribute('aria-pressed')).toBe('true');
  await act(async () => button('Отправить в чаты').click());
  expect(client.post).toHaveBeenCalledWith('/api/availability/campaign', {
    show_names: ['Урод'], dates: ['2026-10-07', '2026-10-10'],
  });
});

test('a month without events still allows adding any date, but cannot send an empty selection', async () => {
  events = [];
  await open();
  expect(button('Отправить в чаты').disabled).toBe(true);
  await act(async () => day(31).click());
  expect(button('Отправить в чаты').disabled).toBe(false);
  await act(async () => day(31).click());
  expect(button('Отправить в чаты').disabled).toBe(true);
});

test('failed loading cannot send stale dates and can be retried', async () => {
  const original = client.get.getMockImplementation();
  client.get.mockImplementation(url => url.endsWith('/next-month-events') ? Promise.reject(new Error('offline')) : original(url));
  await open();
  expect(button('Отправить в чаты').disabled).toBe(true);
  expect(container.textContent).toContain('Не удалось загрузить даты');
  client.get.mockImplementation(original);
  await act(async () => button('Повторить загрузку').click());
  expect(day(3).getAttribute('aria-pressed')).toBe('true');
});

test('date checking uses the edited selection and ignores an outdated response', async () => {
  jest.useFakeTimers();
  try {
    const original = client.get.getMockImplementation();
    let resolveOld;
    client.get.mockImplementation(url => url.endsWith('/check-dates')
      ? new Promise(resolve => { resolveOld = resolve; }) : original(url));
    await open();
    await act(async () => jest.advanceTimersByTime(300));
    const oldResponse = resolveOld;
    await act(async () => day(3).click());
    await act(async () => oldResponse({ data: { missing: ['3 октября'] } }));
    expect(container.textContent).not.toContain('3 октября');
    await act(async () => jest.advanceTimersByTime(300));
    expect(client.get).toHaveBeenLastCalledWith('/api/availability/check-dates', { params: { dates: '2026-10-10' } });
  } finally { jest.useRealTimers(); }
});

test('changing month loads its dates and sends only that month', async () => {
  const original = client.get.getMockImplementation();
  client.get.mockImplementation((url, config) => config?.params?.month
    ? Promise.resolve({ data: { month: config.params.month, events: [{ id: 4, start_time: `${config.params.month}-05T19:00:00+03:00` }] } })
    : original(url));
  await open();
  expect(container.querySelector('input[type="month"]').value).toBe('2026-10');
  await act(async () => day(7).click());
  await act(async () => container.querySelector('[aria-label="Следующий месяц"]').click());
  expect(client.get).toHaveBeenCalledWith('/api/availability/next-month-events', { params: { month: '2026-11' } });
  expect(container.querySelectorAll('.availability-calendar__day')).toHaveLength(30);
  expect(day(5).getAttribute('aria-pressed')).toBe('true');
  expect(day(7).getAttribute('aria-pressed')).toBe('false');
  await act(async () => { day(8).click(); button('Урод').click(); });
  await act(async () => button('Отправить в чаты').click());
  expect(client.post).toHaveBeenCalledWith('/api/availability/campaign', { show_names: ['Урод'], dates: ['2026-11-05', '2026-11-08'] });
  await act(async () => button('Запустить опрос занятости').click());
  expect(container.querySelector('input[type="month"]').value).toBe('2026-10');
});

test('fast month changes ignore late responses, cross the year boundary, and block sending during loading', async () => {
  const original = client.get.getMockImplementation();
  const pending = {};
  client.get.mockImplementation((url, config) => config?.params?.month
    ? new Promise(resolve => { pending[config.params.month] = resolve; }) : original(url));
  await open();
  for (let i = 0; i < 3; i++) {
    await act(async () => container.querySelector('[aria-label="Следующий месяц"]').click());
    expect(button('Отправить в чаты').disabled).toBe(true);
  }
  expect(container.querySelector('input[type="month"]').value).toBe('2027-01');
  await act(async () => pending['2027-01']({ data: { month: '2027-01', events: [] } }));
  await act(async () => pending['2026-11']({ data: { month: '2026-11', events } }));
  expect(container.querySelector('input[type="month"]').value).toBe('2027-01');
  expect(container.textContent).toContain('Выбрано дат: 0');
  await act(async () => { day(1).click(); button('Урод').click(); });
  await act(async () => button('Отправить в чаты').click());
  expect(client.post).toHaveBeenCalledWith('/api/availability/campaign', { show_names: ['Урод'], dates: ['2027-01-01'] });
});

test('partial delivery shows the affected chat and retains selection for a retry', async () => {
  await open();
  await act(async () => button('Урод').click());
  client.post.mockResolvedValue({ data: { status: 'partial', errors: [{ chat_id: -10042, delivery_state: 'failed', error: 'Проверьте права бота' }] } });
  await act(async () => button('Отправить в чаты').click());
  expect(container.textContent).toContain('Чат -10042: Проверьте права бота');
  expect(button('Отправить в чаты')).toBeTruthy();
  expect(day(3).getAttribute('aria-pressed')).toBe('true');
  client.post.mockResolvedValue({ data: { status: 'sent', errors: [] } });
  await act(async () => button('Отправить в чаты').click());
  expect(button('Отправить в чаты')).toBeUndefined();
});

test('retry after an unconfirmed send requires explicit confirmation that no copy appeared', async () => {
  await open();
  await act(async () => button('Урод').click());
  client.post.mockResolvedValue({ data: { status: 'partial', errors: [{ chat_id: -10042, delivery_state: 'uncertain', error: 'Проверьте чат' }] } });
  await act(async () => button('Отправить в чаты').click());
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false);
  try {
    await act(async () => button('Отправить в чаты').click());
    expect(client.post).toHaveBeenCalledTimes(1);
    confirm.mockReturnValue(true);
    client.post.mockResolvedValue({ data: { status: 'sent', errors: [] } });
    await act(async () => button('Отправить в чаты').click());
    expect(client.post).toHaveBeenLastCalledWith('/api/availability/campaign', {
      show_names: ['Урод'], dates: ['2026-10-03', '2026-10-10'], retry_unconfirmed: true,
    });
  } finally { confirm.mockRestore(); }
});
