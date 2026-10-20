import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import ChatMembers from './ChatMembers';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn() } }));
let root, container;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
  client.get.mockResolvedValue({ data: { members: [
    { user_id: 42, name: 'Анна', username: null, status: 'member', revision: 3 },
  ] } });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test('member list displays participants without username and has no exclusion controls', async () => {
  await act(async () => root.render(<ChatMembers chatId={-1001} />));
  expect(container.textContent).toContain('Анна');
  expect(container.textContent).toContain('В группе');
  expect(container.querySelector('input')).toBeNull();
});

test('failed load can be retried and clears the error after recovery', async () => {
  client.get.mockRejectedValueOnce(new Error('offline'));
  await act(async () => root.render(<ChatMembers chatId={-1001} />));
  expect(container.querySelector('[role=alert]').textContent).toContain('Не удалось загрузить');
  await act(async () => container.querySelector('button').click());
  expect(container.querySelector('[role=alert]')).toBeNull();
  expect(container.textContent).toContain('Анна');
  expect(client.get).toHaveBeenCalledTimes(2);
});
