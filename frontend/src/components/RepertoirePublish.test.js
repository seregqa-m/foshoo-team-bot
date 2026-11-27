import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import RepertoirePublish from './RepertoirePublish';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { post: jest.fn() } }));
let root, container;
const data = { month: '2028-10', search_id: 'search', revision: 1, fingerprint: 'fresh' };
const variant = { id: 'variant' };
const targets = ['first', 'second'].map(id => ({ id, title: id, start_time: '2028-10-07T17:00', end_time: '2028-10-07T18:00', location: 'Зал', recurring: true }));
const preview = () => ({ id: 'preview', status: 'preview', done: 0, existing_count: 1, actions: [
  { date: '2028-10-07', kind: 'replace', title: 'Урод [Спект]', start_time: '2028-10-07T19:00', end_time: '2028-10-07T20:30', targets },
  { date: '2028-10-14', kind: 'create', title: 'Другой [Спект]', start_time: '2028-10-14T19:00', end_time: '2028-10-14T20:30', targets: [] },
] });
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; jest.resetAllMocks(); container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); });

test('explicit confirmation requires selecting ambiguous rehearsal and location; double click sends once', async () => {
  client.post.mockResolvedValueOnce({ data: preview() });
  const onApplied = jest.fn();
  await act(async () => root.render(<RepertoirePublish data={data} variant={variant} onApplied={onApplied} onClose={() => {}} />));
  const confirm = button('Подтвердить и обновить календарь');
  expect(confirm.disabled).toBe(true);
  act(() => Simulate.change(container.querySelector('[aria-label="Репетиция 2028-10-07"]'), { target: { value: 'second' } }));
  expect(confirm.disabled).toBe(true);
  act(() => Simulate.change(container.querySelector('[aria-label="Место 2028-10-14"]'), { target: { value: 'Зал 2' } }));
  expect(confirm.disabled).toBe(false);
  expect(container.textContent).toContain('только эта дата серии');
  expect(client.post).toHaveBeenCalledTimes(1);
  let finish;
  client.post.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  act(() => { confirm.click(); confirm.click(); });
  expect(client.post).toHaveBeenLastCalledWith('/api/planning/repertoire/lock', { preview_id: 'preview', choices: { '2028-10-07': 'second' }, locations: { '2028-10-14': 'Зал 2' } });
  expect(client.post).toHaveBeenCalledTimes(2);
  await act(async () => finish({ data: { ...preview(), status: 'complete' } }));
  expect(onApplied).toHaveBeenCalledTimes(1);
});

test('partial publication reopens progress and resumes persisted operation', async () => {
  const publication = { ...preview(), status: 'partial', error: 'Прервано', done: 1 };
  client.post.mockResolvedValue({ data: { ...publication, status: 'complete' } });
  const onApplied = jest.fn();
  await act(async () => root.render(<RepertoirePublish data={data} publication={publication} onApplied={onApplied} onClose={() => {}} />));
  expect(client.post).not.toHaveBeenCalled();
  expect(container.textContent).toContain('Сохранено: 1 из 2');
  expect(container.textContent).toContain('Уже созданные и переименованные события останутся');
  await act(async () => button('Продолжить сохранение').click());
  expect(client.post).toHaveBeenCalledTimes(1);
  expect(onApplied).toHaveBeenCalled();
});

test('closing preview never writes calendar', async () => {
  client.post.mockResolvedValue({ data: preview() });
  const onClose = jest.fn();
  await act(async () => root.render(<RepertoirePublish data={data} variant={variant} onApplied={() => {}} onClose={onClose} />));
  act(() => button('Закрыть').click());
  expect(onClose).toHaveBeenCalled();
  expect(client.post).toHaveBeenCalledTimes(1);
  expect(client.post.mock.calls[0][0]).toBe('/api/planning/repertoire/lock/preview');
});
