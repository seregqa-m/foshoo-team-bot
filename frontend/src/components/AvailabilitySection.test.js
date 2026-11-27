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
  await act(async () => button('Запустить опрос').click());
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
afterEach(() => { act(() => root.unmount()); container.remove(); delete window.Telegram; jest.clearAllMocks(); });

const savedPoll = (id, month = '2027-01') => ({
  id, month, created_at: '2026-11-23T12:00:00', show_names: ['Урод', 'Калий'],
  polls: [-1001, -1002].flatMap((chat, group) => [0, 1, 2].map(part => ({
    id: id * 10 + group * 3 + part, telegram_chat_id: chat, telegram_message_id: 100 + part,
    chat_title: group ? 'Цианистый Калий' : 'Урод', show_names: [group ? 'Калий' : 'Урод'],
    tg_link: `https://t.me/c/${-chat}/${100 + part}`,
    options: [{ date: `${month}-${String(part + 1).padStart(2, '0')}`, date_label: 'скрытая дата' }],
  }))),
});
const article = index => container.querySelectorAll('article')[index];
const chatButton = (index, name) => article(index).querySelector(`[aria-label="Пинг неответивших: ${name}"]`);
const showPolls = async campaigns => {
  client.get.mockResolvedValue({ data: { campaigns } });
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
};

test('shows only the poll title, a gray mini calendar and one first-poll link and ping per chat', async () => {
  await showPolls([savedPoll(2)]);
  expect(article(0).querySelector('h3').textContent).toBe('Опрос на январь 2027 от 23 ноября 2026');
  expect(article(0).querySelectorAll('.poll-summary-calendar__day')).toHaveLength(31);
  expect(article(0).querySelectorAll('.poll-summary-calendar__day--selected')).toHaveLength(3);
  expect(article(0).querySelector('.poll-summary-calendar').querySelector('button')).toBeNull();
  expect(article(0).querySelectorAll('a')).toHaveLength(2);
  expect([...article(0).querySelectorAll('a')].map(a => a.href)).toEqual(['https://t.me/c/1001/100', 'https://t.me/c/1002/100']);
  expect(article(0).querySelectorAll('button')).toHaveLength(2);
  expect(container.querySelector('details')).toBeNull();
  for (const text of ['Блок', 'блок', 'Часть', 'скрытая дата', 'Посмотреть неответивших', '01.01.2027']) {
    expect(container.textContent).not.toContain(text);
  }
  expect(client.post).not.toHaveBeenCalled();
});

test('pings only the selected chat of the selected old poll and blocks repeat clicks', async () => {
  await showPolls([savedPoll(2), savedPoll(1, '2026-12')]);
  let finish;
  client.post.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await act(async () => chatButton(1, 'Цианистый Калий').click());
  expect(chatButton(1, 'Цианистый Калий').disabled).toBe(true);
  expect(chatButton(1, 'Урод').disabled).toBe(false);
  expect(client.post).toHaveBeenCalledWith('/api/availability/ping-non-voters', null, { params: { campaign_id: 1, chat_id: -1002 } });
  await act(async () => chatButton(1, 'Цианистый Калий').click());
  expect(client.post).toHaveBeenCalledTimes(1);
  await act(async () => finish({ data: { count: 2, errors: [] } }));
  expect(article(1).textContent).toContain('Напоминание отправлено');
  expect(article(0).textContent).not.toContain('Напоминание отправлено');
  expect(client.get).toHaveBeenCalledTimes(1);
});

test('opens the selected campaign chat poll through Telegram without browser navigation', async () => {
  window.Telegram = { WebApp: { openTelegramLink: jest.fn() } };
  const older = savedPoll(1, '2026-12');
  older.polls[3].tg_link = 'https://t.me/c/123456/42';
  await showPolls([savedPoll(2), older]);
  const link = article(1).querySelector('[aria-label="Открыть опрос в чате: Цианистый Калий"]');
  const event = new MouseEvent('click', { bubbles: true, cancelable: true });
  await act(async () => link.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(true);
  expect(window.Telegram.WebApp.openTelegramLink).toHaveBeenCalledTimes(1);
  expect(window.Telegram.WebApp.openTelegramLink).toHaveBeenCalledWith('https://t.me/c/123456/42');
  expect(client.post).not.toHaveBeenCalled();
});

test('keeps a normal browser link when the Telegram SDK is unavailable', async () => {
  await showPolls([savedPoll(1)]);
  const link = article(0).querySelector('a');
  let prevented;
  const stopNavigation = event => { prevented = event.defaultPrevented; event.preventDefault(); };
  document.addEventListener('click', stopNavigation);
  try {
    await act(async () => link.click());
    expect(prevented).toBe(false);
    expect(link.target).toBe('_blank');
    expect(link.href).toBe('https://t.me/c/1001/100');
  } finally { document.removeEventListener('click', stopNavigation); }
});

test('failed Telegram navigation shows an error and can be retried', async () => {
  window.Telegram = { WebApp: { openTelegramLink: jest.fn()
    .mockImplementationOnce(() => { throw new Error('unavailable'); }) } };
  await showPolls([savedPoll(1)]);
  const link = article(0).querySelector('a');
  await act(async () => link.click());
  expect(article(0).querySelector('[role="alert"]').textContent).toContain('Не удалось открыть опрос');
  await act(async () => link.click());
  expect(article(0).querySelector('[role="alert"]')).toBeNull();
  expect(window.Telegram.WebApp.openTelegramLink).toHaveBeenCalledTimes(2);
});

test('shows short feedback in the affected chat and does not claim success on error', async () => {
  await showPolls([savedPoll(1)]);
  client.post.mockResolvedValue({ data: { count: 0, errors: [] } });
  await act(async () => chatButton(0, 'Урод').click());
  expect(article(0).textContent).toContain('Нет неответивших');
  client.post.mockRejectedValue({ response: { data: { detail: 'Не удалось проверить состав группы' } } });
  await act(async () => chatButton(0, 'Цианистый Калий').click());
  expect(article(0).querySelector('[role="alert"]').textContent).toContain('Не удалось проверить состав группы');
  expect(article(0).textContent).not.toContain('Напоминание отправлено');
});

test('legacy polls retain their original first link and failed copies are not listed as sent chats', async () => {
  const legacy = savedPoll(1);
  legacy.polls.forEach(p => { p.chat_title = null; p.show_names = null; p.delivery_state = null; });
  legacy.polls = [legacy.polls[0], { ...legacy.polls[3], telegram_message_id: null, tg_link: null }];
  await showPolls([legacy]);
  expect(article(0).querySelectorAll('a')).toHaveLength(1);
  expect(article(0).querySelector('a').href).toBe('https://t.me/c/1001/100');
  expect(article(0).querySelectorAll('button')).toHaveLength(1);
});

test('calendar starts Monday and handles leap February and Moscow creation date', async () => {
  const poll = savedPoll(1, '2028-02');
  poll.created_at = '2026-11-22T22:30:00';
  await showPolls([poll]);
  expect(article(0).querySelector('h3').textContent).toContain('от 23 ноября 2026');
  expect(article(0).querySelectorAll('.poll-summary-calendar__day')).toHaveLength(29);
  const grid = article(0).querySelector('.poll-summary-calendar');
  expect(grid.children[7].getAttribute('aria-hidden')).toBe('true');
  expect(grid.children[8].textContent).toBe('1');
});

test('new sends retain older polls after reloading the screen', async () => {
  const original = client.get.getMockImplementation();
  let saved = [savedPoll(1)];
  client.get.mockImplementation((url, config) => url.endsWith('/campaigns')
    ? Promise.resolve({ data: { campaigns: saved } }) : original(url, config));
  client.post.mockImplementation(() => {
    saved = [savedPoll(2), ...saved];
    return Promise.resolve({ data: { campaign_id: 2 } });
  });
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => button('Новый опрос').click());
  await act(async () => button('Урод').click());
  await act(async () => button('Отправить в чаты').click());
  expect(container.querySelectorAll('article')).toHaveLength(2);
  await act(async () => root.render(null));
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  expect(container.querySelectorAll('article')).toHaveLength(2);
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
  await act(async () => button('Запустить опрос').click());
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
