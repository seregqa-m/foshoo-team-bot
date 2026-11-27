import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import RepertoireDayOptions from './RepertoireDayOptions';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn() } }));
let container, root, onReplace, response;
const data = { fingerprint: 'fresh', revision: 2, checked_at: 'now' };
const show = (key, name, reason = null) => ({ key, name, reason, start_time: '2028-10-07T19:00:00+03:00', covered: 1, total: 1,
  votes: { yes: 1, no: 1, other: 1 }, roles: [{ name: 'Роль', actors: [{ name: 'Анна', status: 'yes', reason: 'Свободен' }, { name: 'Борис', status: 'no', reason: 'Не может' }] }] });
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  onReplace = jest.fn(); response = { day: '2028-10-07', ...data, shows: [show('1', 'Урод'), show('2', 'Другой', 'Нужны ответы исполнителей')] };
  client.get.mockResolvedValue({ data: response });
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
  expect(container.textContent).toContain('Ответы на эту дату · Урод');
  expect(container.textContent).toContain('Кто как ответил');
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

test('background refresh keeps vote cards and expanded details until fresh answers arrive', async () => {
  const entries = [{ date: response.day, key: '1', name: 'Урод' }];
  await render({ entries });
  const card = container.querySelector('.repertoire-day-option');
  const summary = container.querySelector('.repertoire-vote-summary');
  const details = summary.querySelector('details');
  details.open = true;
  let finish;
  client.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await render({ entries, data: { ...data, fingerprint: 'updated', checked_at: 'later' } });
  expect(container.querySelector('.repertoire-day-option')).toBe(card);
  expect(summary.textContent).toContain('Смогут: 1');
  expect(summary.querySelector('details')).toBe(details);
  expect(details.open).toBe(true);
  expect(container.textContent).not.toContain('Загружаем ответы');
  expect(button('Заменить на «Другой»').disabled).toBe(true);
  await act(async () => finish({ data: { ...response, fingerprint: 'updated', shows: [
    { ...response.shows[0], votes: { yes: 2, no: 0, other: 1 } }, show('2', 'Другой'),
  ] } }));
  expect(container.querySelector('.repertoire-day-option')).toBe(card);
  expect(summary.querySelector('details')).toBe(details);
  expect(details.open).toBe(true);
  expect(summary.textContent).toContain('Смогут: 2');
  expect(button('Заменить на «Другой»').disabled).toBe(false);
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

test('selected show has a live answer tile without assigning people to roles', async () => {
  response.shows[0].votes = { yes: 1, no: 0, unknown: 1, unanswered: 2, other: 3 };
  response.shows[0].roles[0].actors[0].vote = 'yes';
  response.shows[0].roles.push({ name: 'Вторая роль', actors: [response.shows[0].roles[0].actors[0]] });
  const current = { date: '2028-10-07', key: '1', name: 'Урод', cast: { Роль: 'Старое назначение' } };
  await render({ entries: [current] });
  let tile = container.querySelector('[aria-label="Ответы на «Урод»"]');
  expect(tile.textContent).toContain('Не определились: 1');
  expect(tile.textContent).toContain('Нет ответа: 2');
  expect(tile.textContent).not.toContain('Старое назначение');
  expect(tile.textContent).not.toContain('Вторая роль');
  expect(tile.textContent.match(/Анна/g)).toHaveLength(1);
  response = { ...response, checked_at: 'later', shows: [{ ...response.shows[0], votes: { yes: 0, no: 1, unknown: 1, unanswered: 2, other: 3 } }] };
  client.get.mockResolvedValue({ data: response });
  await render({ entries: [current], data: { ...data, checked_at: 'later' } });
  tile = container.querySelector('[aria-label="Ответы на «Урод»"]');
  expect(tile.textContent).toContain('Смогут: 0');
  expect(tile.textContent).toContain('Не смогут: 1');
});
