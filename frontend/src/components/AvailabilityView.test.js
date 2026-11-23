import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import AvailabilityView from './AvailabilityView';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn() } }));
jest.mock('./PlanningView', () => ({ initialMonth, onClose, closeLabel, isAdmin }) => <div data-planning-month={initialMonth} data-admin={!!isAdmin}><button onClick={onClose}>{closeLabel}</button></div>);
let container, root;
const button = text => [...container.querySelectorAll('button')].find(b => b.textContent === text);
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  client.get.mockImplementation((url, options) => Promise.resolve({ data: {
    month: options?.params?.month || '2026-12', days: [{ date: '2026-12-19', answer: 'no', revision: 1, editable: true }],
  } }));
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test('calendar is primary; planning opens the selected month and preserves the calendar on return', async () => {
  await act(async () => root.render(<AvailabilityView isAdmin={false} />));
  expect(container.querySelector('[data-planning-month]')).toBeNull();
  const day = container.querySelector('[data-date="2026-12-19"]');
  await act(async () => day.click());
  await act(async () => button('Планирование составов →').click());
  expect(container.querySelector('[data-planning-month]').dataset.planningMonth).toBe('2026-12');
  expect(container.querySelector('[data-planning-month]').dataset.admin).toBe('false');
  expect(day.closest('section').hidden).toBe(true);
  await act(async () => button('← К моим датам').click());
  expect(container.querySelector('[data-planning-month]')).toBeNull();
  expect(day.getAttribute('aria-pressed')).toBe('true');
  expect(day.closest('section').hidden).toBe(false);
});

test('poll result deep link opens planning directly in the requested month', async () => {
  await act(async () => root.render(<AvailabilityView initialPlanningMonth="2027-01" isAdmin />));
  expect(container.querySelector('[data-planning-month]').dataset.planningMonth).toBe('2027-01');
  expect(container.querySelector('[data-planning-month]').dataset.admin).toBe('true');
  expect(client.get).not.toHaveBeenCalled();
  await act(async () => button('← К моим датам').click());
  expect(client.get).toHaveBeenCalledWith('/api/attendance/me', { params: { month: '2027-01' } });
});

test('planning uses the newly chosen month even while personal answers are loading', async () => {
  await act(async () => root.render(<AvailabilityView />));
  client.get.mockImplementationOnce(() => new Promise(() => {}));
  await act(async () => container.querySelector('[aria-label="Следующий месяц"]').click());
  await act(async () => button('Планирование составов →').click());
  expect(container.querySelector('[data-planning-month]').dataset.planningMonth).toBe('2027-01');
});
