import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import MyAvailabilityView from './MyAvailabilityView';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn() } }));

let root, container, data;
const daySection = day => [...container.querySelectorAll('section')].find(s => s.getAttribute('aria-label').includes(day));
const choice = (day, text) => [...daySection(day).querySelectorAll('button')].find(b => b.textContent === text);

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
  data = { month: '2026-12', days: [
    { date: '2026-12-19', answer: 'no', revision: 3, editable: true },
    { date: '2026-12-20', answer: 'yes', revision: 1, editable: true },
  ] };
  client.get.mockImplementation(() => Promise.resolve({ data: JSON.parse(JSON.stringify(data)) }));
  client.put.mockImplementation(async (url, payload) => {
    const row = data.days.find(d => d.date === payload.date);
    row.answer = payload.answer; row.revision += 1;
    return { data: { ...row } };
  });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.resetAllMocks(); });

test('changes only the chosen date and displays the saved answer', async () => {
  await act(async () => root.render(<MyAvailabilityView onClose={() => {}} />));
  expect(choice('19', 'Не могу').getAttribute('aria-pressed')).toBe('true');
  await act(async () => choice('19', 'Могу').click());
  expect(client.put).toHaveBeenCalledWith('/api/attendance/me', {
    date: '2026-12-19', answer: 'yes', expected_revision: 3,
  });
  expect(choice('19', 'Могу').getAttribute('aria-pressed')).toBe('true');
  expect(choice('20', 'Могу').getAttribute('aria-pressed')).toBe('true');
  expect(data.days[1].revision).toBe(1);
  expect(container.textContent).toContain('Сохранено.');
});

test('a concurrent change reloads the actual answer before another choice', async () => {
  client.put.mockImplementation(async () => {
    data.days[0].answer = 'unknown'; data.days[0].revision = 4;
    throw { response: { status: 409 } };
  });
  await act(async () => root.render(<MyAvailabilityView />));
  await act(async () => choice('19', 'Могу').click());
  expect(choice('19', 'Пока не знаю').getAttribute('aria-pressed')).toBe('true');
  expect(container.textContent).toContain('Ответ уже изменился');
  expect(container.textContent).not.toContain('Сохранено.');
});

test('month navigation crosses the year and stale reads cannot replace the new month', async () => {
  await act(async () => root.render(<MyAvailabilityView />));
  let resolveOld;
  client.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await act(async () => container.querySelector('[aria-label="Следующий месяц"]').click());
  client.get.mockResolvedValueOnce({ data: { month: '2027-02', days: [] } });
  await act(async () => container.querySelector('[aria-label="Следующий месяц"]').click());
  await act(async () => resolveOld({ data: { month: '2027-01', days: data.days } }));
  expect(client.get).toHaveBeenCalledWith('/api/attendance/me', { params: { month: '2027-01' } });
  expect(container.querySelector('input').value).toBe('2027-02');
  expect(container.querySelectorAll('section')).toHaveLength(0);
  expect(container.textContent).toContain('пока нет ответов');
});

test('past dates are read-only and load failure never exposes stale answer buttons', async () => {
  data.days[0].editable = false;
  await act(async () => root.render(<MyAvailabilityView />));
  expect(daySection('19').querySelectorAll('button')).toHaveLength(0);
  client.get.mockRejectedValueOnce(new Error('offline'));
  await act(async () => [...container.querySelectorAll('button')].find(b => b.textContent === 'Обновить').click());
  expect(container.querySelector('[role="alert"]').textContent).toContain('Не удалось загрузить');
  expect(container.querySelectorAll('section')).toHaveLength(0);
});

test('a save blocks other writes and ambiguous failure reloads the saved state', async () => {
  let rejectSave;
  client.put.mockImplementationOnce(() => new Promise((resolve, reject) => { rejectSave = reject; }));
  await act(async () => root.render(<MyAvailabilityView />));
  await act(async () => choice('19', 'Могу').click());
  expect(choice('20', 'Не могу').disabled).toBe(true);
  expect(container.querySelector('input').disabled).toBe(true);
  data.days[0].answer = 'yes'; data.days[0].revision = 4;
  await act(async () => rejectSave(new Error('lost response')));
  expect(choice('19', 'Могу').getAttribute('aria-pressed')).toBe('true');
  expect(container.textContent).toContain('Не удалось подтвердить сохранение');
  expect(client.put).toHaveBeenCalledTimes(1);
});
