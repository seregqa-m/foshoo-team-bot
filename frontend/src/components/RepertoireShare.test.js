import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import RepertoireShare from './RepertoireShare';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
let container, root;
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);
const data = { month: '2028-10', search_id: 'search', fingerprint: 'fresh', revision: 2 };
const preview = { id: 'preview', status: 'preview', text: 'План афиши: 7 октября — Урод', chat_title: 'Театр', delivery: 'message' };
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  client.get.mockResolvedValue({ data: { chats: [{ id: -100123, title: 'Театр' }] } });
  client.post.mockResolvedValue({ data: preview });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });
const render = async () => { await act(async () => root.render(<RepertoireShare data={data} variant={{ id: 'chosen-variant' }} onClose={jest.fn()} />)); };
const prepare = async () => {
  act(() => Simulate.change(container.querySelector('select'), { target: { value: '-100123' } }));
  await act(async () => button('Предпросмотр сообщения').click());
};

test('opening never sends, chat selection and exact preview precede explicit send', async () => {
  await render();
  expect(client.post).not.toHaveBeenCalled();
  expect(button('Предпросмотр сообщения').disabled).toBe(true);
  await prepare();
  expect(client.post).toHaveBeenCalledWith('/api/planning/repertoire/share/preview', { month: '2028-10', search_id: 'search', variant_id: 'chosen-variant', chat_id: -100123, expected_fingerprint: 'fresh', expected_revision: 2 });
  expect(container.querySelector('pre').textContent).toBe(preview.text);
  client.post.mockResolvedValue({ data: { ...preview, status: 'sent', link: 'https://t.me/c/123/17' } });
  await act(async () => button('Отправить на согласование').click());
  expect(client.post).toHaveBeenLastCalledWith('/api/planning/repertoire/share/send', { preview_id: 'preview' });
  expect(container.querySelector('a').href).toBe('https://t.me/c/123/17');
  expect(button('Отправить на согласование')).toBeUndefined();
});

test('double click sends once and uncertain delivery disables resending', async () => {
  await render(); await prepare();
  let resolve;
  client.post.mockImplementation(() => new Promise(r => { resolve = r; }));
  const send = button('Отправить на согласование');
  act(() => { send.click(); send.click(); });
  expect(client.post.mock.calls.filter(([url]) => url.endsWith('/send'))).toHaveLength(1);
  await act(async () => resolve({ data: { ...preview, status: 'unknown' } }));
  expect(container.textContent).toContain('повторная отправка заблокирована');
  expect(button('Отправить на согласование')).toBeUndefined();
});

test('stale plan shows server explanation without sending', async () => {
  await render();
  client.post.mockRejectedValue({ response: { data: { detail: 'План изменился. Обновите предложения.' } } });
  await prepare();
  expect(container.querySelector('[role="alert"]').textContent).toContain('План изменился');
  expect(button('Отправить на согласование')).toBeUndefined();
});

test('changing destination discards the previous preview', async () => {
  await render(); await prepare();
  act(() => Simulate.change(container.querySelector('select'), { target: { value: '' } }));
  expect(container.querySelector('pre')).toBeNull();
  expect(button('Отправить на согласование')).toBeUndefined();
});
