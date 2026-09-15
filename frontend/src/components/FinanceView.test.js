import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import FinanceView from './FinanceView';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), delete: jest.fn() } }));
let root, container;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  client.get.mockImplementation(url => Promise.resolve({ data: {
    '/api/finance/meta': { projects: [], actors: [], expense_types: [] },
    '/api/finance/balance': { balance: '5000' },
    '/api/finance/transactions': { transactions: [{ id: 1, type: 'expense', fingerprint: 'current', what: 'Клининг', amount: 5000 }] },
    '/api/finance/chart': { data: [{ period: '09.2026', income: 0, expense_foshu: 5000 }] },
  }[url] }));
  client.delete.mockResolvedValue({ data: {} });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test('delete carries a row fingerprint and refreshes the chart as well as transactions', async () => {
  jest.spyOn(window, 'confirm').mockReturnValue(true);
  await act(async () => root.render(<FinanceView username="actor" isAdmin />));
  const before = client.get.mock.calls.filter(([url]) => url.endsWith('/chart')).length;
  const del = [...container.querySelectorAll('button')].find(b => b.textContent === '×');
  await act(async () => del.click());
  expect(client.delete).toHaveBeenCalledWith('/api/finance/transactions/expense/1', { params: { expected_fingerprint: 'current' } });
  expect(client.get.mock.calls.filter(([url]) => url.endsWith('/chart')).length).toBe(before + 1);
  window.confirm.mockRestore();
});

test('member cannot see deletion controls and sees loading failures', async () => {
  client.get.mockRejectedValue(new Error('offline'));
  await act(async () => root.render(<FinanceView username="actor" isAdmin={false} />));
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect([...container.querySelectorAll('button')].some(b => b.textContent === '×')).toBe(false);
});

test('charts measure their container instead of the browser viewport', async () => {
  const measure = jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 320 });
  await act(async () => root.render(<FinanceView username="actor" isAdmin />));
  expect(container.querySelector('svg').getAttribute('width')).toBe('320');
  measure.mockRestore();
});
