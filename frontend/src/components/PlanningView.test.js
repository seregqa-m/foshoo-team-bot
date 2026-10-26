import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import PlanningView from './PlanningView';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
let root, container, plan;
const button = name => [...container.querySelectorAll('button')].find(b => b.textContent === name);
const actors = [{ name: 'Анна', status: 'yes', reason: 'Свободен' }, { name: 'Борис', status: 'yes', reason: 'Свободен' }];
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  plan = { month: '2028-10', timezone: 'Europe/Moscow', fingerprint: 'reviewed', warnings: [], shows: ['Урод'], slots: [{ column: 'B', date: '2028-10-01', label: '1 окт 2028', assigned_show: '', shows: [{
    show: 'Урод', status: 'ready', covered: 2, total: 2, incomplete: false,
    roles: [{ name: 'Летте', actors }, { name: 'Фанни', actors: [actors[0]] }], suggested_cast: { Летте: 'Борис', Фанни: 'Анна' },
  }] }] };
  client.get.mockImplementation(url => Promise.resolve({ data: url === '/api/availability/current'
    ? { campaign: null } : url === '/api/sheets/shows' ? { shows: ['Урод'] } : plan }));
  client.post.mockResolvedValue({ data: {} });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });
const open = async () => {
  await act(async () => root.render(<PlanningView onClose={() => {}} isAdmin />));
  await act(async () => container.querySelector('.planning-cell').click());
};

test('loads the linked month immediately and lets the user change it', async () => {
  plan.month = '2026-12';
  await act(async () => root.render(<PlanningView onClose={() => {}} initialMonth="2026-12" />));
  expect(client.get).toHaveBeenCalledTimes(1);
  expect(client.get).toHaveBeenCalledWith('/api/planning', { params: { month: '2026-12' } });
  expect(container.querySelector('input[type="month"]').value).toBe('2026-12');
  await act(async () => container.querySelector('[aria-label="Следующий месяц планирования"]').click());
  expect(client.get).toHaveBeenLastCalledWith('/api/planning', { params: { month: '2027-01' } });
});

test('uses the server default month and marks today in the planning timezone at the UTC month boundary', async () => {
  const clock = jest.spyOn(Date, 'now').mockReturnValue(new Date('2028-09-30T21:05:00Z').getTime());
  try {
    await act(async () => root.render(<PlanningView onClose={() => {}} />));
    expect(client.get).toHaveBeenCalledWith('/api/planning', undefined);
    expect(container.querySelector('input[type="month"]').value).toBe('2028-10');
    expect(container.querySelector('[aria-current="date"]').textContent).toContain('Сегодня1 окт 2028');
    clock.mockReturnValue(new Date('2028-10-01T21:05:00Z').getTime());
    await act(async () => window.dispatchEvent(new Event('focus')));
    expect(container.querySelector('[aria-current="date"]')).toBeNull();
    act(() => Simulate.change(container.querySelector('input[type="month"]'), { target: { value: '2028-11' } }));
    await act(async () => {});
    expect(client.get).toHaveBeenLastCalledWith('/api/planning', { params: { month: '2028-11' } });
  } finally {
    clock.mockRestore();
  }
});

test('shows role coverage and submits the chosen cast, time, location and reviewed snapshot', async () => {
  await open();
  expect(button('Запустить опрос занятости')).toBeDefined();
  expect(container.textContent).toContain('2/2');
  expect(container.querySelector('[aria-label="Исполнитель: Летте"]').value).toBe('Борис');
  const place = container.querySelector('input[placeholder="Зал или адрес"]');
  act(() => Simulate.change(place, { target: { value: 'Малая сцена' } }));
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(client.post).toHaveBeenCalledWith('/api/planning/assign', {
    month: '2028-10', column: 'B', show_name: 'Урод', cast: { Летте: 'Борис', Фанни: 'Анна' },
    expected_fingerprint: 'reviewed', start_time: '2028-10-01T19:00', end_time: '2028-10-01T21:00', location: 'Малая сцена',
  });
  expect(container.textContent).toContain('Спектакль создан в расписании');
});

test('one actor cannot be selected for two roles', async () => {
  await open();
  act(() => Simulate.change(container.querySelector('[aria-label="Исполнитель: Летте"]'), { target: { value: 'Анна' } }));
  expect(button('Назначить спектакль').disabled).toBe(true);
  expect(container.textContent).toContain('Один актёр выбран на несколько ролей');
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(client.post).not.toHaveBeenCalled();
});

test('changed votes require refresh before any retry', async () => {
  client.post.mockRejectedValue({ response: { status: 409, data: { detail: 'График изменился' } } });
  await open();
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(container.textContent).toContain('График изменился');
  expect(button('Назначить спектакль').disabled).toBe(true);
  expect(button('Обновить сводку')).toBeDefined();
});

test('unfinished save restores its exact payload instead of creating a different event', async () => {
  plan.slots[0].operation = { status: 'calendar_created', show_name: 'Урод', cast: { Летте: 'Борис', Фанни: 'Анна' }, start_time: '2028-10-01T18:00:00+03:00', end_time: '2028-10-01T20:00:00+03:00', location: 'Зал' };
  await open();
  expect(container.querySelector('input[type="datetime-local"]').disabled).toBe(true);
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(client.post.mock.calls[0][1].start_time).toBe('2028-10-01T18:00:00+03:00');
});

test('failed source read is an error rather than an empty available cast', async () => {
  client.get.mockRejectedValue(new Error('offline'));
  await act(async () => root.render(<PlanningView onClose={() => {}} />));
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect(container.querySelector('.planning-cell')).toBeNull();
});

test('attendance is visible without roles but cannot bypass cast assignment requirements', async () => {
  Object.assign(plan.slots[0].shows[0], {
    roles: [], total: 0, covered: 0, incomplete: true, status: 'blocked', suggested_cast: {},
    attendance: { total: 12, yes: 8, no: 2, unknown: 1, unanswered: 1 },
  });
  await open();
  expect(container.textContent).toContain('Участников: 12');
  expect(container.textContent).toContain('смогут: 8');
  expect(container.textContent).toContain('не ответили: 1');
  expect(button('Назначить спектакль')).toBeUndefined();
  expect(client.post).not.toHaveBeenCalled();
});

test.each([false, true])('members can inspect roles and answers but cannot assign or resume (pending: %s)', async pending => {
  if (pending) plan.slots[0].operation = { status: 'calendar_created', show_name: 'Урод', cast: { Летте: 'Борис', Фанни: 'Анна' }, start_time: '2028-10-01T18:00:00+03:00', end_time: '2028-10-01T20:00:00+03:00', location: 'Зал' };
  await act(async () => root.render(<PlanningView onClose={() => {}} initialMonth="2028-10" />));
  expect(container.textContent).not.toContain('Опрос занятости');
  expect(client.get).not.toHaveBeenCalledWith('/api/availability/current', undefined);
  await act(async () => container.querySelector('.planning-cell').click());
  const dialog = container.querySelector('[role="dialog"]');
  expect(dialog.textContent).toContain('Летте');
  expect(dialog.textContent).toContain('Анна: Свободен');
  expect(dialog.querySelector('form')).toBeNull();
  expect(dialog.querySelector('select, input, button[type="submit"]')).toBeNull();
  expect(client.post).not.toHaveBeenCalled();
});

test('losing admin access removes assignment controls in an already open dialog', async () => {
  await open();
  expect(button('Назначить спектакль')).toBeDefined();
  await act(async () => root.render(<PlanningView onClose={() => {}} isAdmin={false} />));
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  expect(button('Назначить спектакль')).toBeUndefined();
  expect(container.querySelector('form')).toBeNull();
  expect(client.post).not.toHaveBeenCalled();
});
