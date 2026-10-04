import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import TheaterPanel from './TheaterPanel';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), put: jest.fn() } }));
let root, container, data;
const button = text => [...container.querySelectorAll('button')].find(item => item.textContent === text);
const field = label => container.querySelector(`[aria-label="${label}"]`);
const open = async () => { await act(async () => root.render(<TheaterPanel />)); };
const change = async (label, value) => { await act(async () => Simulate.change(field(label), { target: { value } })); };
const submit = async label => { await act(async () => Simulate.submit(field(label))); };

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  data = { shows: [{ id: 1, name: 'Урод', telegram_chat_id: null, revision: 0 }],
    chats: [{ telegram_chat_id: -1001, title: 'Урод — чат', checked_at: '2026-10-03T10:00:00Z' }], audit: [] };
  client.get.mockImplementation(() => Promise.resolve({ data }));
  client.post.mockResolvedValue({ data: { added: 1, title: 'Урод — чат' } });
  client.put.mockImplementation((url, payload) => {
    const id = Number(url.split('/').pop());
    const updated = { id, name: payload.name, telegram_chat_id: payload.telegram_chat_id,
      revision: payload.expected_revision + 1 };
    data = { ...data, shows: data.shows.map(show => show.id === id ? updated : show) };
    return Promise.resolve({ data: updated });
  });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.resetAllMocks(); });

test('route is changed only on explicit save and includes the revision', async () => {
  await open();
  expect([...container.querySelectorAll('th')].map(cell => cell.textContent)).toEqual(['Спектакль', 'ID чата']);
  expect(container.querySelector('select')).toBeNull();
  await change('ID чата: Урод', '-1002');
  expect(client.put).not.toHaveBeenCalled();
  await submit('Настройки спектакля Урод');
  expect(client.put).toHaveBeenCalledWith('/api/admin/theater/shows/1', {
    name: 'Урод', telegram_chat_id: -1002, expected_revision: 0,
  });
  expect(container.textContent).toContain('Сохранено');
  expect(client.post).not.toHaveBeenCalled();
  expect(field('Настройки спектакля Урод').querySelector('button').disabled).toBe(true);
});

test('removing a route sends null, not the legacy group', async () => {
  data.shows[0].telegram_chat_id = -1001;
  await open();
  await change('ID чата: Урод', '');
  await submit('Настройки спектакля Урод');
  expect(client.put.mock.calls[0][1].telegram_chat_id).toBeNull();
});

test('stale edit reloads latest data and keeps the server error visible', async () => {
  await open();
  await change('ID чата: Урод', '-1001');
  data = { ...data, shows: [{ ...data.shows[0], revision: 1, name: 'Урод новый' }] };
  client.put.mockRejectedValue({ response: { status: 409, data: { detail: 'Настройки изменил другой администратор' } } });
  await submit('Настройки спектакля Урод');
  expect(container.querySelector('[role="alert"]').textContent).toContain('другой администратор');
  expect(field('Название: Урод новый').value).toBe('Урод новый');
  expect(field('Настройки спектакля Урод новый').querySelector('button').disabled).toBe(true);
});

test('invalid chat ID does not send a request', async () => {
  await open();
  for (const value of ['@group', '123', '-1e3', '-9007199254740992', '-4503599627370496']) {
    await change('ID чата: Урод', value);
    await submit('Настройки спектакля Урод');
  }
  expect(client.put).not.toHaveBeenCalled();
  await change('ID чата: Урод', '  -1001  ');
  await submit('Настройки спектакля Урод');
  expect(client.put.mock.calls[0][1].telegram_chat_id).toBe(-1001);
});

test('denied catalog hides all editing controls', async () => {
  client.get.mockRejectedValue({ response: { status: 403, data: { detail: 'Нет глобальных прав' } } });
  await open();
  expect(container.querySelector('form')).toBeNull();
  expect(container.textContent).toContain('Нет глобальных прав');
});

test('import is explicit and reports added shows', async () => {
  await open();
  expect(client.post).not.toHaveBeenCalled();
  await act(async () => button('Импортировать спектакли из таблицы').click());
  expect(client.post).toHaveBeenCalledWith('/api/admin/theater/shows/import');
  expect(container.textContent).toContain('Добавлено спектаклей: 1');
});

test('saving one row preserves the unsaved ID in another row', async () => {
  data.shows.push({ id: 2, name: 'Слепые', telegram_chat_id: null, revision: 0 });
  await open();
  await change('ID чата: Слепые', '-1002');
  await change('ID чата: Урод', '-1001');
  await submit('Настройки спектакля Урод');
  expect(field('ID чата: Слепые').value).toBe('-1002');
  await submit('Настройки спектакля Слепые');
  expect(client.put.mock.calls[1][1].telegram_chat_id).toBe(-1002);
});

test('failed chat verification keeps the draft and allows retrying', async () => {
  await open();
  client.put.mockRejectedValueOnce({ response: { status: 502, data: { detail: 'Не удалось проверить чат' } } });
  await change('ID чата: Урод', '-1002');
  await submit('Настройки спектакля Урод');
  expect(field('ID чата: Урод').value).toBe('-1002');
  expect(container.textContent).toContain('Не удалось проверить чат');
  expect(field('Настройки спектакля Урод').querySelector('button').disabled).toBe(false);
  await submit('Настройки спектакля Урод');
  expect(container.textContent).toContain('Сохранено');
});
