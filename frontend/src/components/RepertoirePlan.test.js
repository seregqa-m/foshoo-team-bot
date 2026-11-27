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
  jest.resetAllMocks();
  localStorage.clear();
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  response = fixture();
  client.get.mockImplementation((url, options) => Promise.resolve({ data: url.endsWith('/day')
    ? { day: options.params.day, fingerprint: response.fingerprint, revision: response.revision, shows: [] } : response }));
  client.put.mockResolvedValue({ data: { revision: 3 } });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); jest.useRealTimers(); });
const render = async props => { await act(async () => root.render(<RepertoirePlan key={`${props?.month || '2028-10'}:${props?.userId || ''}`} month="2028-10" isSuperAdmin={true} {...props} />)); };

test('shows maximum partial plan, shortfall and per-role reasons; switches alternatives', async () => {
  await render();
  expect(container.textContent).toContain('1 из 2');
  expect(container.textContent).toContain('Не хватает: Урод — 1');
  expect(container.textContent).toContain('Нужны ответы исполнителей');
  expect(container.textContent).toContain('Анна — Нет ответа');
  expect(container.textContent).toContain('Вариант 1 из 2');
  expect(container.querySelector('[aria-label="Вариант расписания"]')).toBeNull();
  await act(async () => container.querySelector('[aria-label="Следующий вариант"]').click());
  expect(container.querySelector('[aria-label="Удалить Урод, 2028-10-08"]')).not.toBeNull();
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
  expect(client.get.mock.calls.filter(([url]) => url === '/api/planning/repertoire').at(-1)).toEqual(['/api/planning/repertoire', { params: { month: '2032-06' } }]);
  act(() => button('Параметры').click());
  expect(container.textContent).toContain('Правила на 2032-06');
});

test('shortlist uses arrows, hides the exhaustive count and preserves choice while searching', async () => {
  jest.useFakeTimers();
  response.considered_variants = 80; response.complete = false;
  response.variants[1].changes = [{ key: 'catalog:1', name: 'Урод', from: ['2028-10-07'], to: ['2028-10-08'] }];
  await render();
  expect(container.textContent).toContain('Подбираем лучшие варианты');
  expect(container.textContent).not.toContain('80');
  expect(container.textContent).not.toContain('Страница');
  await act(async () => container.querySelector('[aria-label="Следующий вариант"]').click());
  expect(container.textContent).toContain('Вариант 2 из 2');
  expect(container.textContent).toContain('Отличия от рекомендованного');
  expect(container.textContent).toContain('7 окт. → 8 окт.');
  response = { ...response, selected_variant: response.variants[1] };
  await act(async () => jest.advanceTimersByTime(1000));
  expect(client.get.mock.calls.filter(([url]) => url === '/api/planning/repertoire').at(-1)).toEqual(['/api/planning/repertoire', { params: { month: '2028-10', selected: 'second' } }]);
  expect(container.textContent).toContain('Вариант 2 из 2');
});

test('reading votes pins the viewed variant even when a newer recommendation arrives in flight', async () => {
  jest.useFakeTimers();
  await render();
  const originalGet = client.get.getMockImplementation();
  let finishRefresh;
  client.get.mockImplementation((url, options) => url === '/api/planning/repertoire'
    ? new Promise(resolve => { finishRefresh = resolve; }) : originalGet(url, options));
  await act(async () => jest.advanceTimersByTime(30_000));
  await act(async () => container.querySelector('[data-date="2028-10-20"]').click());
  const newer = { ...response, variants: [response.variants[1], response.variants[0]], recommended_id: 'second', selected_variant: response.variants[0] };
  client.get.mockImplementation((url, options) => url === '/api/planning/repertoire' ? Promise.resolve({ data: newer }) : originalGet(url, options));
  await act(async () => finishRefresh({ data: { ...response, variants: [response.variants[1]], selected_variant: null } }));
  expect(client.get.mock.calls.filter(([url]) => url === '/api/planning/repertoire').at(-1)[1].params.selected).toBe('first');
  expect(container.querySelector('[data-date="2028-10-20"]').getAttribute('aria-pressed')).toBe('true');
});

test('refreshes answers automatically and blocks actions on stale data', async () => {
  jest.useFakeTimers();
  await render();
  const before = client.get.mock.calls.length;
  client.get.mockRejectedValue(new Error('offline'));
  await act(async () => jest.advanceTimersByTime(30_000));
  expect(client.get.mock.calls.length).toBe(before + 1);
  expect(container.textContent).toContain('Показаны последние полученные данные');
  expect(button('Удалить из афиши').disabled).toBe(true);
  expect(button('Закрепить афишу месяца').disabled).toBe(true);
});

test('whole month lock opens reviewed calendar confirmation without applying it', async () => {
  client.post.mockResolvedValue({ data: { id: 'preview', status: 'preview', actions: [], existing_count: 0 } });
  await render();
  await act(async () => button('Закрепить афишу месяца').click());
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  expect(client.post).toHaveBeenCalledWith('/api/planning/repertoire/lock/preview', { month: '2028-10', search_id: 'search', variant_id: 'first', expected_fingerprint: 'fresh', expected_revision: 2 });
  expect(client.post.mock.calls.some(([url]) => url === '/api/planning/repertoire/lock')).toBe(false);
  expect(container.textContent).toContain('Снятие закрепления не откатит изменения календаря');
});

test('existing pin can be removed even when no valid variant remains', async () => {
  response.rules.pins = [{ day: '2028-10-07', key: 'catalog:1' }];
  response.pin_errors = ['Закреплённый спектакль больше не подходит']; response.variants = []; response.total_variants = 0;
  await render();
  client.post.mockResolvedValue({ data: { locked: false } });
  await act(async () => button('Снять закрепление').click());
  expect(client.post).toHaveBeenCalledWith('/api/planning/repertoire/unlock', { month: '2028-10', expected_revision: 2 });
});

test('labels a rehearsal slot and explains how calendar assignment works', async () => {
  response.variants[0].entries[0].rehearsals = [{ event_id: 42, title: 'Урод [Реп]' }];
  await render();
  expect(container.textContent).toContain('Репетиционный слот');
  expect(container.textContent).toContain('для любого спектакля с полным составом');
  expect([...container.querySelectorAll('summary')].some(s => s.textContent === 'Состав')).toBe(false);
  expect(container.textContent).not.toContain('Летте — Анна');
  expect(container.textContent).not.toContain('Состав собран');
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
  await act(async () => container.querySelector('[aria-label="Следующий вариант"]').click());
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

test('empty calendar cells show votes and a local addition survives automatic refresh', async () => {
  jest.useFakeTimers();
  client.get.mockImplementation((url, options) => Promise.resolve({ data: url.endsWith('/day') ? {
    day: options.params.day, fingerprint: response.fingerprint, revision: response.revision,
    shows: [{ key: 'catalog:2', name: 'Другой', reason: null, covered: 1, total: 1, votes: { yes: 1, no: 0, other: 0 },
      roles: [{ name: 'Роль', actors: [{ name: 'Борис', reason: 'Свободен', status: 'yes' }] }] }],
  } : response }));
  const added = { date: '2028-10-10', key: 'catalog:2', name: 'Другой', cast: { Роль: 'Борис' }, fixed: false };
  const manual = { ...response.variants[0], id: 'manual', manual: true, entries: [...response.variants[0].entries, added], excess: [{ name: 'Другой', count: 1 }] };
  client.post.mockResolvedValue({ data: { status: 'ready', variant: manual } });
  await render();
  await act(async () => container.querySelector('[data-date="2028-10-10"]').click());
  expect(container.textContent).toContain('Борис — Свободен');
  await act(async () => button('Поставить «Другой»').click());
  expect(client.post).toHaveBeenLastCalledWith('/api/planning/repertoire/draft', { month: '2028-10', expected_fingerprint: 'fresh', expected_revision: 2,
    entries: [{ day: '2028-10-07', key: 'catalog:1' }, { day: '2028-10-10', key: 'catalog:2' }] });
  expect(container.querySelector('[data-date="2028-10-10"]').getAttribute('aria-pressed')).toBe('true');
  expect(container.querySelector('[data-date="2028-10-07"]').getAttribute('aria-label')).toContain('Урод');
  expect(container.textContent).toContain('Сверх плана: Другой — 1');
  await act(async () => jest.advanceTimersByTime(30_000));
  expect(container.textContent).toContain('Ручной вариант');
  expect(container.querySelector('[data-date="2028-10-10"]').getAttribute('aria-label')).toContain('Другой');
  client.post.mockRejectedValue({ response: { data: { detail: 'Ответы изменились' } } });
  await act(async () => window.dispatchEvent(new Event('focus')));
  expect(container.textContent).toContain('Ответы изменились');
  expect(button('Отправить в чат').disabled).toBe(true);
  await act(async () => button('Отменить ручные изменения').click());
  expect(container.querySelector('[data-date="2028-10-10"]').getAttribute('aria-label')).toContain('Нет показов');
});

test('calendar and date answers remain available before any automatic variant is found', async () => {
  response.variants = []; response.total_variants = 0; response.maximum = null; response.complete = false;
  await render();
  expect(container.querySelectorAll('[data-date]')).toHaveLength(31);
  await act(async () => container.querySelector('[data-date="2028-10-20"]').click());
  expect(client.get).toHaveBeenLastCalledWith('/api/planning/repertoire/day', { params: { month: '2028-10', day: '2028-10-20' } });
});

test('saved manual dates are revalidated on reopen and isolated between users and months', async () => {
  const entries = [{ day: '2028-10-20', key: 'catalog:1' }];
  localStorage.setItem('foshoo:repertoire-draft:42:2028-10', JSON.stringify(entries));
  const manual = { ...response.variants[0], id: 'restored', manual: true, entries: [{ ...response.variants[0].entries[0], date: '2028-10-20' }] };
  client.post.mockResolvedValue({ data: { status: 'ready', variant: manual } });
  await render({ userId: 42 });
  expect(client.post).toHaveBeenCalledWith('/api/planning/repertoire/draft', expect.objectContaining({ entries }));
  expect(container.querySelector('[data-date="2028-10-20"]').getAttribute('aria-label')).toContain('Урод');
  const reviewed = client.post.mock.calls.length;
  await render({ userId: 43 });
  expect(client.post.mock.calls.length).toBe(reviewed);
  expect(container.querySelector('[data-date="2028-10-20"]').getAttribute('aria-label')).toContain('Нет показов');
  await render({ userId: 42 });
  await act(async () => button('Отменить ручные изменения').click());
  expect(localStorage.getItem('foshoo:repertoire-draft:42:2028-10')).toBeNull();
});


test('deleting last recommendation leaves an empty draft and survives reopen', async () => {
  const manual = { ...response.variants[0], id: 'empty', manual: true, entries: [], count: 0, missing: [{ key: 'catalog:1', name: 'Урод', count: 2 }] };
  client.post.mockResolvedValue({ data: { status: 'ready', variant: manual } });
  await render({ userId: 42 });
  await act(async () => button('Удалить из афиши').click());
  expect(client.post).toHaveBeenCalledWith('/api/planning/repertoire/draft', expect.objectContaining({ entries: [] }));
  expect(container.querySelector('[data-date="2028-10-07"]').getAttribute('aria-label')).toContain('Нет показов');
  expect(container.textContent).toContain('Не хватает: Урод — 2');
  expect(localStorage.getItem('foshoo:repertoire-draft:42:2028-10')).toBe('[]');
  await render({ userId: 43 }); await render({ userId: 42 });
  expect(container.querySelector('[data-date="2028-10-07"]').getAttribute('aria-label')).toContain('Нет показов');
});

test('only superadmin can lock or unlock; locked month keeps votes available', async () => {
  await render({ isSuperAdmin: false });
  expect(button('Закрепить афишу месяца')).toBeUndefined();
  response.locked = true; response.selected_variant = response.variants[0];
  await render({ isSuperAdmin: false, userId: 43 });
  expect(button('Снять закрепление')).toBeUndefined();
  expect(button('Удалить из афиши').disabled).toBe(true);
  expect(button('Параметры').disabled).toBe(true);
  await act(async () => container.querySelector('[data-date="2028-10-20"]').click());
  expect(client.get).toHaveBeenLastCalledWith('/api/planning/repertoire/day', { params: { month: '2028-10', day: '2028-10-20' } });
});

test('server locked calendar wins over local draft and remains unlockable when invalid', async () => {
  localStorage.setItem('foshoo:repertoire-draft:42:2028-10', JSON.stringify([{ day: '2028-10-20', key: 'catalog:1' }]));
  response.locked = true; response.lock_error = 'Календарь изменился'; response.selected_variant = response.variants[0];
  await render({ userId: 42 });
  expect(client.post).not.toHaveBeenCalled();
  expect(localStorage.getItem('foshoo:repertoire-draft:42:2028-10')).toBeNull();
  expect(container.textContent).toContain('Календарь изменился');
  expect(button('Снять закрепление').disabled).toBe(false);
  expect(button('Отправить в чат').disabled).toBe(true);
});
