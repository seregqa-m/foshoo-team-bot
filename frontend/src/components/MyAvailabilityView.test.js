import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import MyAvailabilityView from './MyAvailabilityView';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn() } }));
let root, container, data;
const cell = date => container.querySelector(`[data-date="${date}"]`);
const choice = text => [...container.querySelectorAll('.my-availability__answers button')].find(b => b.textContent === text);
const select = date => act(async () => cell(date).click());

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
  data = { month: '2026-12', days: [
    { date: '2026-12-19', answer: 'no', revision: 3, editable: true },
    { date: '2026-12-20', answer: 'yes', revision: 1, editable: true },
    { date: '2026-12-23', answer: 'unknown', revision: 1, editable: true },
    { date: '2026-12-27', answer: null, revision: 2, editable: true },
  ] };
  client.get.mockImplementation(() => Promise.resolve({ data: JSON.parse(JSON.stringify(data)) }));
  client.put.mockImplementation(async (url, payload) => {
    const row = data.days.find(d => d.date === payload.date);
    row.answer = payload.answer; row.revision += 1;
    return { data: { ...row } };
  });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.resetAllMocks(); });

test('shows a Monday-first month with answer colors and accessible labels', async () => {
  await act(async () => root.render(<MyAvailabilityView />));
  expect(container.querySelectorAll('[data-date]')).toHaveLength(31);
  const grid = container.querySelector('.my-availability__calendar');
  expect(grid.children[7].hasAttribute('aria-hidden')).toBe(true); // December 1 is Tuesday.
  expect(grid.children[8]).toBe(cell('2026-12-01'));
  expect(cell('2026-12-19').className).toContain('--no');
  expect(cell('2026-12-20').className).toContain('--yes');
  expect(cell('2026-12-23').className).toContain('--unknown');
  expect(cell('2026-12-01').className).toContain('--unanswered');
  expect(cell('2026-12-19').getAttribute('aria-label')).toContain('Не могу');
  expect(client.put).not.toHaveBeenCalled();
});

test('changes only the selected date and updates its calendar color', async () => {
  await act(async () => root.render(<MyAvailabilityView />));
  await select('2026-12-19');
  expect(choice('Не могу').getAttribute('aria-pressed')).toBe('true');
  await act(async () => choice('Могу').click());
  expect(client.put).toHaveBeenCalledWith('/api/attendance/me', {
    date: '2026-12-19', answer: 'yes', expected_revision: 3,
  });
  expect(cell('2026-12-19').className).toContain('--yes');
  expect(cell('2026-12-19').getAttribute('aria-pressed')).toBe('true');
  expect(data.days[1].revision).toBe(1);
  expect(container.textContent).toContain('Сохранено.');
});

test('a concurrent change reloads the actual answer before another choice', async () => {
  client.put.mockImplementation(async () => {
    data.days[0].answer = 'unknown'; data.days[0].revision = 4;
    throw { response: { status: 409 } };
  });
  await act(async () => root.render(<MyAvailabilityView />));
  await select('2026-12-19');
  await act(async () => choice('Могу').click());
  expect(choice('Пока не знаю').getAttribute('aria-pressed')).toBe('true');
  expect(cell('2026-12-19').className).toContain('--unknown');
  expect(container.textContent).toContain('Ответ уже изменился');
  expect(container.textContent).not.toContain('Сохранено.');
});

test('navigation crosses the year, clears selection and rejects late reads', async () => {
  await act(async () => root.render(<MyAvailabilityView />));
  await select('2026-12-19');
  let resolveOld;
  client.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await act(async () => container.querySelector('[aria-label="Следующий месяц"]').click());
  client.get.mockResolvedValueOnce({ data: { month: '2027-02', days: [] } });
  await act(async () => container.querySelector('[aria-label="Следующий месяц"]').click());
  await act(async () => resolveOld({ data: { month: '2027-01', days: data.days } }));
  expect(client.get).toHaveBeenCalledWith('/api/attendance/me', { params: { month: '2027-01' } });
  expect(container.querySelector('input').value).toBe('2027-02');
  expect(container.querySelectorAll('[data-date]')).toHaveLength(28);
  expect(container.querySelector('.my-availability__selection')).toBeNull();
  expect(container.textContent).toContain('пока нет ответов');
});

test('past and unrecorded days are read-only, while a retracted answer can be changed', async () => {
  data.days[0].editable = false;
  await act(async () => root.render(<MyAvailabilityView />));
  await select('2026-12-19');
  expect(choice('Могу')).toBeUndefined();
  expect(container.textContent).toContain('Дата прошла');
  await select('2026-12-01');
  expect(choice('Могу')).toBeUndefined();
  expect(container.textContent).toContain('вы ещё не отвечали');
  await select('2026-12-27');
  expect(choice('Могу').disabled).toBe(false);
});

test('load failure never exposes stale answer controls', async () => {
  await act(async () => root.render(<MyAvailabilityView />));
  await select('2026-12-19');
  client.get.mockRejectedValueOnce(new Error('offline'));
  await act(async () => [...container.querySelectorAll('button')].find(b => b.textContent === 'Обновить').click());
  expect(container.querySelector('[role="alert"]').textContent).toContain('Не удалось загрузить');
  expect(choice('Могу')).toBeUndefined();
});

test('save blocks other choices and ambiguous failure reloads the saved state', async () => {
  let rejectSave;
  client.put.mockImplementationOnce(() => new Promise((resolve, reject) => { rejectSave = reject; }));
  await act(async () => root.render(<MyAvailabilityView />));
  await select('2026-12-19');
  await act(async () => choice('Могу').click());
  expect(cell('2026-12-20').disabled).toBe(true);
  expect(container.querySelector('input').disabled).toBe(true);
  data.days[0].answer = 'yes'; data.days[0].revision = 4;
  await act(async () => rejectSave(new Error('lost response')));
  expect(cell('2026-12-19').className).toContain('--yes');
  expect(container.textContent).toContain('Не удалось подтвердить сохранение');
  expect(client.put).toHaveBeenCalledTimes(1);
});

test('leap February includes all 29 dates', async () => {
  client.get.mockResolvedValue({ data: { month: '2028-02', days: [] } });
  await act(async () => root.render(<MyAvailabilityView initialMonth="2028-02" />));
  expect(container.querySelectorAll('[data-date]')).toHaveLength(29);
  expect(cell('2028-02-29')).not.toBeNull();
});

const chooseParticipant = value => act(async () => {
  const selector = container.querySelector('select');
  selector.value = value;
  selector.dispatchEvent(new Event('change', { bubbles: true }));
});
const people = [{ telegram_user_id: 99, name: 'Катя', username: 'katya' },
  { telegram_user_id: 100, name: 'Маша', username: '' }];
const mockParticipants = () => {
  client.get.mockImplementation(url => Promise.resolve({ data: url === '/api/attendance/participants'
    ? { participants: people, incomplete: false }
    : url === '/api/attendance/me' ? data
      : { month: '2026-12', today: '2026-11-23', can_create: true, days: [] } }));
};

test('ordinary users have no participant selection or roster request', async () => {
  await act(async () => root.render(<MyAvailabilityView />));
  expect(container.querySelector('select')).toBeNull();
  expect(client.get).toHaveBeenCalledTimes(1);
});

test('superadmin selects a named participant and creates an answer without a poll', async () => {
  mockParticipants();
  client.put.mockResolvedValue({ data: { date: '2026-12-01', answer: 'no', revision: 1, editable: true } });
  await act(async () => root.render(<MyAvailabilityView isSuperAdmin />));
  expect(container.querySelector('select').textContent).toContain('Катя (@katya)');
  await chooseParticipant('99');
  expect(container.textContent).toContain('Вы отвечаете за: Катя');
  expect(client.get).toHaveBeenLastCalledWith('/api/attendance/participants/99', { params: { month: '2026-12' } });
  await select('2026-12-01');
  await act(async () => choice('Не могу').click());
  expect(client.put).toHaveBeenCalledWith('/api/attendance/participants/99', {
    date: '2026-12-01', answer: 'no', expected_revision: 0,
  });
  expect(container.textContent).toContain('Катя —');
});

test('switching people clears answers and ignores a late response for the previous person', async () => {
  mockParticipants();
  await act(async () => root.render(<MyAvailabilityView isSuperAdmin />));
  let resolveOld;
  client.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await chooseParticipant('99');
  expect(cell('2026-12-19')).toBeNull();
  await chooseParticipant('100');
  await act(async () => resolveOld({ data }));
  expect(cell('2026-12-19').className).toContain('--unanswered');
  expect(container.textContent).toContain('Вы отвечаете за: Маша');
  await chooseParticipant('');
  expect(cell('2026-12-19').className).toContain('--no');
  expect(container.textContent).not.toContain('Вы отвечаете за:');
});

test('participant selection is blocked during save and conflicts reload target answers', async () => {
  mockParticipants();
  let rejectSave;
  client.put.mockImplementationOnce(() => new Promise((resolve, reject) => { rejectSave = reject; }));
  await act(async () => root.render(<MyAvailabilityView isSuperAdmin />));
  await chooseParticipant('99');
  await select('2026-12-01');
  await act(async () => choice('Не могу').click());
  expect(container.querySelector('select').disabled).toBe(true);
  client.get.mockResolvedValueOnce({ data: { ...data, today: '2026-11-23', can_create: true,
    days: [{ date: '2026-12-01', answer: 'yes', revision: 1, editable: true }] } });
  await act(async () => rejectSave({ response: { status: 409 } }));
  expect(cell('2026-12-01').className).toContain('--yes');
  expect(container.textContent).toContain('Ответ уже изменился');
  expect(container.querySelector('select').disabled).toBe(false);
});

test('unrecorded past dates stay read-only for superadmins', async () => {
  mockParticipants();
  await act(async () => root.render(<MyAvailabilityView isSuperAdmin />));
  client.get.mockResolvedValueOnce({ data: { month: '2026-11', today: '2026-11-23', can_create: true, days: [] } });
  await chooseParticipant('99');
  // Selection preserves the month already viewed; explicitly move to November.
  client.get.mockResolvedValueOnce({ data: { month: '2026-11', today: '2026-11-23', can_create: true, days: [] } });
  await act(async () => container.querySelector('[aria-label="Предыдущий месяц"]').click());
  await select('2026-11-22');
  expect(choice('Могу')).toBeUndefined();
  await select('2026-11-23');
  expect(choice('Могу').disabled).toBe(false);
});

test('failed roster load leaves personal answers available with a retry message', async () => {
  mockParticipants();
  client.get.mockImplementationOnce(() => Promise.reject(new Error('offline')));
  await act(async () => root.render(<MyAvailabilityView isSuperAdmin />));
  expect(container.textContent).toContain('Не удалось загрузить участников');
  expect(cell('2026-12-19')).not.toBeNull();
});
