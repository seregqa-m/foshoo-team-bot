import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import RepertoirePlan from './RepertoirePlan';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn(), post: jest.fn() } }));
let container, root, response;
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);
const fixture = () => ({
  month: '2028-10', search_id: 'search', maximum: 1, target: 2, total_variants: 2, complete: true, page: 0, page_size: 20,
  revision: 2, defaults_revision: 1, fingerprint: 'fresh', checked_at: '2028-09-01T14:32:00+03:00', timezone: 'Europe/Moscow',
  shows: [{ key: 'catalog:1', name: 'Урод' }], rules: { shows: [{ key: 'catalog:1', count: 2, weekdays: [0, 1, 2, 3, 4, 5, 6], spread: true, gap: 14, start: null }], pins: [], streak: 3, load_mode: 'prefer' },
  diagnostics: [{ key: 'catalog:1', name: 'Урод', ready_dates: ['2028-10-07'], dates: [{ date: '2028-10-08', reason: 'Нужны ответы исполнителей', roles: [{ name: 'Летте', actors: [{ name: 'Анна', reason: 'Нет ответа' }] }] }] }], warnings: [], pin_errors: [],
  variants: ['first', 'second'].map((id, i) => ({ id, count: 1, entries: [{ date: `2028-10-0${i + 7}`, key: 'catalog:1', name: 'Урод', cast: { Летте: 'Анна' }, fixed: false }],
    missing: [{ key: 'catalog:1', name: 'Урод', count: 1 }], load_score: 0, spread_score: 0, load_warnings: [], spread_warnings: [] })),
});
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  response = fixture();
  client.get.mockImplementation(() => Promise.resolve({ data: response }));
  client.put.mockResolvedValue({ data: { revision: 3 } });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); jest.useRealTimers(); });
const render = async props => { await act(async () => root.render(<RepertoirePlan key={props?.month || '2028-10'} month="2028-10" {...props} />)); };

test('shows maximum partial plan, shortfall and per-role reasons; switches alternatives', async () => {
  await render();
  expect(container.textContent).toContain('1 из 2');
  expect(container.textContent).toContain('Не хватает: Урод — 1');
  expect(container.textContent).toContain('Нужны ответы исполнителей');
  expect(container.textContent).toContain('Анна — Нет ответа');
  const select = container.querySelector('[aria-label="Вариант расписания"]');
  expect(select.options.length).toBe(2);
  act(() => Simulate.change(select, { target: { value: 'second' } }));
  expect(container.querySelector('[aria-label="Закрепить Урод, 2028-10-08"]')).not.toBeNull();
});

test('edits month rules without duration and saves the reviewed revision', async () => {
  await render();
  act(() => button('Параметры').click());
  expect(container.textContent.toLowerCase()).not.toContain('длительность');
  expect([...container.querySelectorAll('label')].find(l => l.textContent.includes('Разносить показы')).querySelector('input').checked).toBe(true);
  act(() => container.querySelector('[aria-label="Больше показов: Урод"]').click());
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(client.put).toHaveBeenCalledWith('/api/planning/repertoire', expect.objectContaining({ month: '2028-10', expected_revision: 2, expected_defaults_revision: 1, use_as_default: false,
    rules: expect.objectContaining({ shows: [expect.objectContaining({ count: 3, spread: true })] }) }));
});

test('conflicting parameters require reload instead of overwriting a different administrator', async () => {
  await render();
  act(() => button('Параметры').click());
  client.put.mockRejectedValue({ response: { status: 409, data: { detail: 'Параметры изменены другим администратором' } } });
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(button('Сохранить параметры').disabled).toBe(true);
  expect(button('Загрузить актуальные параметры')).toBeDefined();
  expect(container.textContent).toContain('Параметры изменены другим администратором');
});

test('future month loads without horizon limit and old response does not replace it', async () => {
  let resolveOld;
  client.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await render();
  response = { ...fixture(), month: '2032-06' };
  await render({ month: '2032-06' });
  await act(async () => resolveOld({ data: fixture() }));
  expect(client.get).toHaveBeenLastCalledWith('/api/planning/repertoire', { params: { month: '2032-06', page: 0 } });
  act(() => button('Параметры').click());
  expect(container.textContent).toContain('Правила на 2032-06');
});

test('pagination exposes all found variants and unfinished search is explicit', async () => {
  response.total_variants = 41; response.complete = false;
  await render();
  expect(container.textContent).toContain('Перебор продолжается');
  expect(container.textContent).toContain('Страница 1 из 3');
  response = { ...response, page: 1 };
  await act(async () => button('→').click());
  expect(client.get).toHaveBeenLastCalledWith('/api/planning/repertoire', { params: { month: '2028-10', page: 1 } });
  expect(container.textContent).toContain('Страница 2 из 3');
});

test('refreshes answers automatically and blocks actions on stale data', async () => {
  jest.useFakeTimers();
  await render();
  const before = client.get.mock.calls.length;
  client.get.mockRejectedValue(new Error('offline'));
  await act(async () => jest.advanceTimersByTime(30_000));
  expect(client.get.mock.calls.length).toBe(before + 1);
  expect(container.textContent).toContain('Показаны последние полученные данные');
  expect(button('Перейти к назначению').disabled).toBe(true);
  expect(button('Закрепить').disabled).toBe(true);
});

test('pins date with optimistic revision and prepares assignment with fresh snapshot', async () => {
  const onPrepared = jest.fn();
  client.post.mockResolvedValue({ data: { plan: {}, column: 'B', show: 'Урод' } });
  await render({ onPrepared });
  await act(async () => button('Перейти к назначению').click());
  expect(client.post).toHaveBeenCalledWith('/api/planning/repertoire/prepare', { month: '2028-10', day: '2028-10-07', key: 'catalog:1', expected_fingerprint: 'fresh', expected_revision: 2 });
  expect(onPrepared).toHaveBeenCalledWith({ plan: {}, column: 'B', show: 'Урод' }, { Летте: 'Анна' });
  await act(async () => button('Закрепить').click());
  expect(client.put.mock.calls[0][1].rules.pins).toEqual([{ day: '2028-10-07', key: 'catalog:1' }]);
});

test('existing pin can be removed even when no valid variant remains', async () => {
  response.rules.pins = [{ day: '2028-10-07', key: 'catalog:1' }];
  response.pin_errors = ['Закреплённый спектакль больше не подходит']; response.variants = []; response.total_variants = 0;
  await render();
  await act(async () => button('Снять закрепление').click());
  expect(client.put.mock.calls[0][1].rules.pins).toEqual([]);
});

test('labels a rehearsal slot and explains how calendar assignment works', async () => {
  response.variants[0].entries[0].rehearsals = [{ event_id: 42, title: 'Урод [Реп]' }];
  await render();
  expect(container.textContent).toContain('Репетиционный слот');
  expect(container.textContent).toContain('для любого спектакля с полным составом');
  expect(container.textContent).toContain('В календаре: Урод [Реп]');
  expect(container.textContent).toContain('Репетиция автоматически не меняется');
  expect(container.textContent).not.toContain('Даты с событиями календаря заняты');
});

test('opening another variant for sharing resets the previous preview', async () => {
  client.get.mockImplementation(url => Promise.resolve({ data: url.endsWith('/chats') ? { chats: [{ id: -100123, title: 'Театр' }] } : response }));
  client.post.mockResolvedValue({ data: { id: 'preview-first', text: 'Первый вариант', status: 'preview', chat_title: 'Театр' } });
  await render();
  await act(async () => button('Отправить в чат').click());
  act(() => Simulate.change(container.querySelector('[aria-label="Чат для согласования"]'), { target: { value: '-100123' } }));
  await act(async () => button('Предпросмотр сообщения').click());
  expect(container.querySelector('pre').textContent).toBe('Первый вариант');
  act(() => Simulate.change(container.querySelector('[aria-label="Вариант расписания"]'), { target: { value: 'second' } }));
  await act(async () => button('Отправить в чат').click());
  expect(container.querySelector('pre')).toBeNull();
  act(() => Simulate.change(container.querySelector('[aria-label="Чат для согласования"]'), { target: { value: '-100123' } }));
  await act(async () => button('Предпросмотр сообщения').click());
  expect(client.post).toHaveBeenLastCalledWith('/api/planning/repertoire/share/preview', expect.objectContaining({ variant_id: 'second' }));
});

test('large format keeps Friday available, disallows Monday–Thursday and has no duration control', async () => {
  await render();
  act(() => button('Параметры').click());
  act(() => Simulate.change(container.querySelector('[aria-label="Формат: Урод"]'), { target: { value: 'large' } }));
  const days = [...container.querySelector('[aria-label="Дни: Урод"]').querySelectorAll('button')];
  expect(days.slice(0, 4).every(b => b.disabled)).toBe(true);
  expect(days[4].disabled).toBe(false);
  expect(container.textContent).toContain('пт — 19:00, сб–вс — 18:00');
  expect(container.textContent.toLowerCase()).not.toContain('длительность');
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(client.put.mock.calls[0][1].rules.shows[0]).toEqual(expect.objectContaining({ format: 'large', weekdays: [4, 5, 6] }));
});
