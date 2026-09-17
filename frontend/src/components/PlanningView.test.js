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
  client.get.mockResolvedValue({ data: plan }); client.post.mockResolvedValue({ data: {} });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });
const open = async () => {
  await act(async () => root.render(<PlanningView onClose={() => {}} />));
  await act(async () => container.querySelector('.planning-cell').click());
};

test('shows role coverage and submits the chosen cast, time, location and reviewed snapshot', async () => {
  await open();
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
