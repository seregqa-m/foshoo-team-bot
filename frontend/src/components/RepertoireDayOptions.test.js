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
  expect(container.textContent).toContain('Выбран в этом варианте');
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
