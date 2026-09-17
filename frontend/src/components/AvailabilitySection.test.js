import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { AvailabilitySection } from './NotificationsView';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
let root, container, events;
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);
const day = n => container.querySelectorAll('.availability-calendar__day')[n - 1];
const open = async () => {
  await act(async () => root.render(<AvailabilitySection showNames={['Урод']} />));
  await act(async () => button('Запустить опрос занятости для спектов').click());
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
    '/api/availability/current': { campaign: null },
    '/api/availability/next-month-events': { month: '2026-10', events },
    '/api/availability/check-dates': { missing: [] },
  }[url] }));
  client.post.mockResolvedValue({ data: {} });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test('preselects unique calendar dates and sends only the final selected dates', async () => {
  await open();
  expect(container.querySelectorAll('.availability-calendar__day')).toHaveLength(31);
  expect(day(3).getAttribute('aria-pressed')).toBe('true');
  expect(day(10).getAttribute('aria-pressed')).toBe('true');
  expect(container.textContent).toContain('Выбрано дат: 2');
  await act(async () => { day(3).click(); day(7).click(); button('Урод').click(); });
  expect(day(3).getAttribute('aria-pressed')).toBe('false');
  expect(day(7).getAttribute('aria-pressed')).toBe('true');
  await act(async () => button('Отправить в чат').click());
  expect(client.post).toHaveBeenCalledWith('/api/availability/campaign', {
    show_names: ['Урод'], dates: ['2026-10-07', '2026-10-10'],
  });
});

test('a month without events still allows adding any date, but cannot send an empty selection', async () => {
  events = [];
  await open();
  expect(button('Отправить в чат').disabled).toBe(true);
  await act(async () => day(31).click());
  expect(button('Отправить в чат').disabled).toBe(false);
  await act(async () => day(31).click());
  expect(button('Отправить в чат').disabled).toBe(true);
});

test('failed loading cannot send stale dates and can be retried', async () => {
  const original = client.get.getMockImplementation();
  client.get.mockImplementation(url => url.endsWith('/next-month-events') ? Promise.reject(new Error('offline')) : original(url));
  await open();
  expect(button('Отправить в чат').disabled).toBe(true);
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
