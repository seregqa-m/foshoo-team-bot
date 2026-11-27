import React, { act } from 'react';
import { Simulate } from 'react-dom/test-utils';
import { createRoot } from 'react-dom/client';
import RepertoireDayOptions from './RepertoireDayOptions';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
let container, root, onReplace, response, plan;
const data = { fingerprint: 'fresh', revision: 2, checked_at: 'now' };
const show = (key, name, reason = null) => ({ key, name, reason, start_time: '2028-10-07T19:00:00+03:00', covered: 1, total: 1,
  votes: { yes: 1, no: 1, other: 1 }, roles: [{ name: 'Роль', actors: [{ name: 'Анна', status: 'yes', reason: 'Свободен' }, { name: 'Борис', status: 'no', reason: 'Не может' }] }] });
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  onReplace = jest.fn(); response = { day: '2028-10-07', ...data, shows: [show('1', 'Урод'), show('2', 'Другой', 'Нужны ответы исполнителей')] };
  plan = { month: '2028-10', fingerprint: 'planning-fresh', timezone: 'Europe/Moscow', slots: [{
    column: 'B', date: response.day, label: '7 окт 2028', assigned_show: '', shows: [{
      show: 'Урод', status: 'ready', incomplete: false, roles: response.shows[0].roles,
      suggested_cast: { Роль: 'Анна' }, attendance: { total: 3, yes: 1, no: 1, unknown: 0, unanswered: 1 },
    }],
  }] };
  client.get.mockImplementation(url => Promise.resolve({ data: url === '/api/planning' ? plan : response }));
  client.post.mockResolvedValue({ data: {} });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });
const render = async props => { await act(async () => root.render(<RepertoireDayOptions month="2028-10" day="2028-10-07" data={data} entries={[]} onReplace={onReplace} onRefresh={jest.fn()} {...props} />)); };
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);

test('an empty date shows all casts and votes, with an action to add an eligible show', async () => {
  await render();
  expect(container.textContent).toContain('Анна — Свободен');
  expect(container.textContent).toContain('Борис — Не может');
  expect(container.textContent).toContain('Смогут: 1 · Не смогут: 1');
  expect(button('Поставить «Другой»').disabled).toBe(true);
  act(() => button('Поставить «Урод»').click());
  expect(onReplace).toHaveBeenCalledWith('2028-10-07', '1');
});

test('a planned date offers replacements while a fixed show remains read-only', async () => {
  response.shows[1].reason = null;
  const current = { date: '2028-10-07', key: '1' };
  await render({ entries: [current] });
  expect(button('Посмотреть голоса и состав · Урод')).toBeDefined();
  expect(button('Заменить на «Другой»').disabled).toBe(false);
  await render({ entries: [{ ...current, fixed: true }] });
  expect(button('Заменить на «Другой»').disabled).toBe(true);
  expect(container.textContent).toContain('Анна — Свободен');
});

test('new answers cannot be applied against an older monthly snapshot', async () => {
  response.fingerprint = 'new-vote';
  await render();
  expect(button('Поставить «Урод»').disabled).toBe(true);
  expect(container.querySelector('[role="alert"]').textContent).toContain('обновились');
});

test('late response from a previously selected date is ignored', async () => {
  let resolveOld;
  client.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await render();
  client.get.mockResolvedValue({ data: { ...response, day: '2028-10-08', shows: [show('3', 'Новая дата')] } });
  await render({ day: '2028-10-08' });
  await act(async () => resolveOld({ data: response }));
  expect(container.textContent).toContain('Новая дата');
  expect(container.textContent).not.toContain('Урод');
});

test('background refresh keeps alternatives mounted and blocks opening stale answers', async () => {
  const entries = [{ date: response.day, key: '1', name: 'Урод' }];
  await render({ entries });
  const card = container.querySelector('.repertoire-day-option');
  const details = card.querySelector('details');
  details.open = true;
  let finish;
  client.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await render({ entries, data: { ...data, fingerprint: 'updated', checked_at: 'later' } });
  expect(container.querySelector('.repertoire-day-option')).toBe(card);
  expect(details.open).toBe(true);
  expect(button('Посмотреть голоса и состав · Урод').disabled).toBe(true);
  await act(async () => finish({ data: { ...response, fingerprint: 'updated' } }));
  expect(container.querySelector('.repertoire-day-option')).toBe(card);
  expect(details.open).toBe(true);
  expect(button('Посмотреть голоса и состав · Урод').disabled).toBe(false);
});

test('failed background refresh retains answers for reading but blocks replacement', async () => {
  await render();
  expect(button('Поставить «Урод»').disabled).toBe(false);
  client.get.mockRejectedValueOnce(new Error('offline'));
  await render({ data: { ...data, checked_at: 'later' } });
  expect(container.textContent).toContain('Анна — Свободен');
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect(button('Поставить «Урод»').disabled).toBe(true);
});

test('changing the date never displays answers from the previous date while loading', async () => {
  await render();
  client.get.mockImplementationOnce(() => new Promise(() => {}));
  await render({ day: '2028-10-08' });
  expect(container.textContent).toContain('Загружаем ответы');
  expect(container.textContent).not.toContain('Анна');
  expect(container.querySelector('.repertoire-day-option')).toBeNull();
});

test('opens the existing cast dialog with fresh planning answers and saves through its usual endpoint', async () => {
  const onRefresh = jest.fn(), onCastSaved = jest.fn();
  await render({ entries: [{ date: response.day, key: '1', name: 'Урод' }], onRefresh, onCastSaved });
  await act(async () => button('Посмотреть голоса и состав · Урод').click());
  const dialog = container.querySelector('[role="dialog"]');
  expect(dialog.textContent).toContain('Участников: 3');
  expect(dialog.textContent).toContain('Каждая роль — отдельный исполнитель');
  expect(dialog.textContent).toContain('Анна: Свободен');
  expect(dialog.querySelector('[aria-label="Исполнитель: Роль"]').value).toBe('Анна');
  expect(dialog.querySelector('option[value="Борис"]').disabled).toBe(true);
  act(() => Simulate.change(dialog.querySelector('input[placeholder="Зал или адрес"]'), { target: { value: 'Зал' } }));
  await act(async () => Simulate.submit(dialog.querySelector('form')));
  expect(client.post).toHaveBeenCalledWith('/api/planning/assign', expect.objectContaining({
    column: 'B', show_name: 'Урод', expected_fingerprint: 'planning-fresh', cast: { Роль: 'Анна' },
  }));
  expect(onRefresh).toHaveBeenCalledTimes(1);
  expect(onCastSaved).toHaveBeenCalledTimes(1);
  expect(container.querySelector('[role="dialog"]')).toBeNull();
});

test('a date absent from Sheets uses the same dialog without preparing or assigning a column', async () => {
  response.planning_slot = { date: response.day, label: '7 окт 2028', assigned_show: '' };
  response.shows[0].planning_cell = plan.slots[0].shows[0];
  plan.slots = [];
  await render({ entries: [{ date: response.day, key: '1', name: 'Урод' }] });
  await act(async () => button('Посмотреть голоса и состав · Урод').click());
  expect(container.querySelector('[role="dialog"]').textContent).toContain('Анна: Свободен');
  expect(container.querySelector('[aria-label="Исполнитель: Роль"]').disabled).toBe(true);
  expect(button('Назначить спектакль')).toBeUndefined();
  expect(client.post).not.toHaveBeenCalled();
  act(() => container.querySelector('[aria-label="Закрыть состав"]').click());
  expect(container.querySelector('[role="dialog"]')).toBeNull();
});

test('a late cast response cannot open a dialog for a previously selected date', async () => {
  await render({ entries: [{ date: response.day, key: '1', name: 'Урод' }] });
  let finish;
  client.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await act(async () => button('Посмотреть голоса и состав · Урод').click());
  await render({ day: '2028-10-08' });
  await act(async () => finish({ data: plan }));
  expect(container.querySelector('[role="dialog"]')).toBeNull();
});

test('failed cast loading reports the error and allows retry', async () => {
  await render({ entries: [{ date: response.day, key: '1', name: 'Урод' }] });
  client.get.mockRejectedValueOnce(new Error('offline'));
  await act(async () => button('Посмотреть голоса и состав · Урод').click());
  expect(container.querySelector('[role="alert"]').textContent).toContain('Не удалось загрузить состав');
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  await act(async () => button('Посмотреть голоса и состав · Урод').click());
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
});
