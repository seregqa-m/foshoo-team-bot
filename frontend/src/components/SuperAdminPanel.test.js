import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import SuperAdminPanel from './SuperAdminPanel';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
let root, container, admins;
const sergey = { telegram_user_id: 42, username: 'sergey', display_name: 'Сергей' };
const masha = { telegram_user_id: 84, username: 'masha', display_name: 'Маша' };
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);
const open = async () => { await act(async () => root.render(<SuperAdminPanel currentUserId={42} />)); };
const search = async query => {
  await act(async () => Simulate.change(container.querySelector('input'), { target: { value: query } }));
  await act(async () => jest.advanceTimersByTime(300));
};

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  jest.useFakeTimers();
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  admins = [sergey];
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/superadmins')
    ? { admins, audit: [] } : { users: [masha] } }));
  client.post.mockResolvedValue({ data: {} });
  client.delete.mockResolvedValue({ data: {} });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.resetAllMocks(); jest.useRealTimers(); });

test('last superadmin cannot be removed in the UI', async () => {
  await open();
  expect(container.textContent).toContain('Сергей (вы)');
  expect(button('Снять глобальные права').disabled).toBe(true);
});

test('grant requires selecting and confirming the specific Telegram identity', async () => {
  await open();
  await search('Маша');
  expect(client.get).toHaveBeenCalledWith('/api/admin/users', { params: { q: 'Маша' } });
  expect(client.post).not.toHaveBeenCalled();
  await act(async () => button('Маша · ID 84').click());
  expect(container.textContent).toContain('Этот человек получит полные права');
  expect(client.post).not.toHaveBeenCalled();
  admins = [sergey, masha];
  await act(async () => button('Назначить суперадминистратором').click());
  expect(client.post).toHaveBeenCalledWith('/api/admin/superadmins', { telegram_user_id: 84 });
  expect(container.textContent).toContain('Маша — теперь суперадминистратор');
  expect(button('Снять глобальные права').disabled).toBe(false);
});

test('revoke requires confirmation and preserves a server rejection after refresh', async () => {
  admins = [sergey, masha];
  await open();
  await act(async () => button('Снять глобальные права').click());
  expect(client.delete).not.toHaveBeenCalled();
  client.delete.mockRejectedValue({ response: { data: { detail: 'Нельзя удалить последнего суперадминистратора' } } });
  admins = [sergey];
  await act(async () => button('Подтвердить снятие').click());
  expect(client.delete).toHaveBeenCalledTimes(1);
  expect(client.delete).toHaveBeenCalledWith('/api/admin/superadmins/42');
  expect(container.querySelector('[role="alert"]').textContent).toContain('Нельзя удалить последнего');
  expect(button('Снять глобальные права').disabled).toBe(true);
});

test('stale search response cannot select a different person', async () => {
  await open();
  let resolveOld;
  client.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await search('Сергей');
  await search('Маша');
  await act(async () => resolveOld({ data: { users: [sergey] } }));
  expect(button('Сергей · ID 42')).toBeUndefined();
  expect(button('Маша · ID 84')).toBeDefined();
});

test('denied list does not expose management controls', async () => {
  client.get.mockRejectedValue({ response: { status: 403, data: { detail: 'Нет глобальных прав' } } });
  await open();
  expect(container.querySelector('input')).toBeNull();
  expect(container.textContent).toContain('Нет глобальных прав');
});
