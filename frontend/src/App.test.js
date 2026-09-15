import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import App from './App';
import client, { DATA_CHANGED_EVENT } from './api/client';

jest.mock('./api/client', () => ({ __esModule: true, default: { get: jest.fn() }, DATA_CHANGED_EVENT: 'foshoo:data-changed' }));
jest.mock('./components/AssistantView', () => {
  const React = require('react');
  return function MockAssistant() {
    const [value, setValue] = React.useState('');
    return <input aria-label="draft" value={value} onChange={e => setValue(e.target.value)} />;
  };
});
jest.mock('./components/FinanceView', () => () => <div>finance</div>);
jest.mock('./components/CalendarView', () => () => <div>calendar</div>);
jest.mock('./components/LinksView', () => () => <div>links</div>);
jest.mock('./components/NotificationsView', () => () => <div>settings</div>);

let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/check') ? { allowed: true, is_admin: true, user_id: 42, username: 'actor' } : { troupe_filter: 'труппа 1' } }));
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test('switching tabs preserves the assistant draft', async () => {
  await act(async () => root.render(<App />));
  const draft = container.querySelector('input');
  act(() => Simulate.change(draft, { target: { value: 'Клининг 5000' } }));
  const buttons = container.querySelectorAll('nav button');
  act(() => buttons[2].click());
  expect(draft.closest('section').hidden).toBe(true);
  act(() => buttons[0].click());
  expect(container.querySelector('input')).toBe(draft);
  expect(draft.value).toBe('Клининг 5000');
});

test('failed access check does not open the application', async () => {
  client.get.mockRejectedValue({ response: { data: { detail: 'Проверка доступа недоступна' } } });
  await act(async () => root.render(<App />));
  expect(container.querySelector('nav')).toBeNull();
  expect(container.textContent).toContain('Проверка доступа недоступна');
});

test('mutations refresh the shared troupe filter', async () => {
  await act(async () => root.render(<App />));
  const before = client.get.mock.calls.filter(([url]) => url.endsWith('app-config')).length;
  await act(async () => window.dispatchEvent(new Event(DATA_CHANGED_EVENT)));
  expect(client.get.mock.calls.filter(([url]) => url.endsWith('app-config')).length).toBe(before + 1);
});
