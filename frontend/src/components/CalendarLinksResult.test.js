import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import CalendarLinksResult from './CalendarLinksResult';
import AssistantView from './AssistantView';
import { assistantApi } from '../api/client';

jest.mock('../api/client', () => ({ assistantApi: {
  hints: jest.fn(), chat: jest.fn(), execute: jest.fn(),
}, uploadAfisha: jest.fn() }));
let root, container;
const links = [{ name: 'FoShoo — Урод + Калий', show_ids: [1, 2], url: 'https://example.org/api/calendar/feeds/test.ics', webcal_url: 'webcal://example.org/api/calendar/feeds/test.ics' }];
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  assistantApi.hints.mockResolvedValue([]);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: jest.fn().mockResolvedValue() } });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test('shows shared URLs directly and copies names with links without app-login links', async () => {
  await act(async () => root.render(<CalendarLinksResult links={links} />));
  expect(container.querySelector('a').getAttribute('href')).toBe(links[0].webcal_url);
  expect(container.querySelector('textarea').value).toContain(links[0].url);
  await act(async () => button('Копировать все ссылки').click());
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(`${links[0].name}\n${links[0].url}`);
  expect(container.querySelector('[role=status]').textContent).toContain('скопированы');
});

test('assistant displays actual execution URLs rather than only the generic done message', async () => {
  assistantApi.chat.mockResolvedValueOnce({ reply: 'Проверьте набор', pending_action: {
    action_token: 'token', tool_name: 'rebuild_calendar_links',
    preview: { title: 'Создать общую календарную ссылку', lines: ['Урод + Калий'], warnings: [] },
  } }).mockResolvedValue({ reply: 'Всё готово!' });
  assistantApi.execute.mockResolvedValue({ success: true, result: { calendar_links: links } });
  await act(async () => root.render(<AssistantView userId={42} username="admin" />));
  await act(async () => Simulate.change(container.querySelector('textarea'), { target: { value: 'Ссылка на Урод и Калий' } }));
  await act(async () => container.querySelector('[aria-label="Отправить"]').click());
  expect(container.querySelector('[aria-label="Ссылки для отправки"]')).toBeNull();
  await act(async () => button('Выполнить').click());
  expect(assistantApi.execute).toHaveBeenCalledWith({ userId: 42, actionToken: 'token' });
  expect(container.querySelector('[aria-label="Ссылки для отправки"]').value).toContain(links[0].url);
  expect(button('Выполнено').disabled).toBe(true);
});
