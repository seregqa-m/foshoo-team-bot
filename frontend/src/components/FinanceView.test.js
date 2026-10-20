import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import FinanceView from './FinanceView';
import client from '../api/client';

jest.mock('../api/client', () => ({ __esModule: true, default: { get: jest.fn(), delete: jest.fn(), post: jest.fn() } }));
let root, container, responses;
const button = name => [...container.querySelectorAll('button')].find(b => b.textContent === name);
const change = (selector, value) => act(() => Simulate.change(container.querySelector(selector), { target: { value } }));
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  responses = {
    '/api/finance/meta': { projects: ['Театр'], actors: ['Дарья Шарыгина', 'Анна Иванова'],
      expense_types: ['Личные траты', 'Трата со счета ФоШу', 'Возврат', 'Пожертвование'] },
    '/api/finance/whoami': { name: 'Дарья Шарыгина' },
    '/api/finance/balance': { balance: '5000' },
    '/api/finance/transactions': { transactions: [{ id: 1, type: 'expense', fingerprint: 'current', what: 'Клининг', amount: 5000 }] },
    '/api/finance/chart': { data: [{ period: '09.2026', income: 0, expense_foshu: 5000 }] },
    '/api/finance/reimbursements': { total: 1300, people: [
      { who: 'Анна Иванова', amount: 1000 }, { who: 'Дарья Шарыгина', amount: 300 },
    ], unassigned: { personal: 0, returned: 0 }, recent: {
      total: 200, people: [{ who: 'Анна Иванова', amount: 200 }],
      unassigned: { personal: 0, returned: 0 }, from_date: '2026-09-21', to_date: '2026-10-20',
    } },
    '/api/finance/reimbursements/history': { transactions: [
      { id: 2, date: '2026-10-20', amount: 300, expense_type: 'Возврат', what: 'Компенсация', project: 'Театр', comment: '' },
      { id: 1, date: '2026-10-19', amount: 500, expense_type: 'Личные траты', what: 'Реквизит', project: 'Урод', comment: 'Для спектакля' },
    ] },
  };
  client.get.mockImplementation(url => Promise.resolve({ data: responses[url] }));
  client.delete.mockResolvedValue({ data: {} });
  client.post.mockResolvedValue({ data: {} });
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
  expect(client.get.mock.calls.filter(([url]) => url.endsWith('/reimbursements')).length).toBe(before + 1);
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
  await act(async () => button('Статистика').click());
  expect(container.querySelector('svg').getAttribute('width')).toBe('320');
  measure.mockRestore();
});

test('three summaries share one place and chart controls survive switching', async () => {
  await act(async () => root.render(<FinanceView username="actor" isAdmin />));
  expect(container.querySelector('[aria-label="Сводка финансов"]').querySelectorAll('button')).toHaveLength(3);
  expect(button('Копилка').getAttribute('aria-pressed')).toBe('true');
  expect(container.querySelector('svg')).toBeNull();
  await act(async () => button('Статистика').click());
  await act(async () => button('История').click());
  await act(async () => button('К возврату').click());
  expect(container.querySelector('svg')).toBeNull();
  expect(container.textContent).toContain('Личные траты минус возвраты за тот же период');
  expect(container.textContent).toContain((1300).toLocaleString('ru-RU') + ' ₽');
  expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
  expect(container.querySelector('tbody').textContent).toContain('Анна Иванова');
  await act(async () => button('Статистика').click());
  expect(button('История').style.background).toBe('rgb(17, 17, 17)');
  expect(container.querySelector('input[type="date"]')).toBeNull();
});

test('reimbursements show two amount columns without a visible person header and open complete history', async () => {
  await act(async () => root.render(<FinanceView username="actor" />));
  await act(async () => button('К возврату').click());
  expect([...container.querySelectorAll('th')].map(th => th.textContent)).toEqual(['', 'Всё время', '30 дней']);
  const cells = [...container.querySelector('tbody tr').children].map(td => td.textContent);
  expect(cells).toEqual(['Анна Иванова', (1000).toLocaleString('ru-RU') + ' ₽', '200 ₽']);
  await act(async () => button('Анна Иванова').click());
  expect(client.get).toHaveBeenCalledWith('/api/finance/reimbursements/history', expect.objectContaining({
    params: { who: 'Анна Иванова' },
  }));
  const dialog = container.querySelector('[role="dialog"]');
  expect(dialog.textContent).toContain('Для спектакля');
  expect([...dialog.querySelectorAll('li')].map(li => li.textContent)).toEqual([
    expect.stringContaining('Возврат−300 ₽Компенсация20.10.2026'),
    expect.stringContaining('Личная трата+500 ₽Реквизит19.10.2026'),
  ]);
  await act(async () => button('Закрыть').click());
  expect(container.querySelector('[role="dialog"]')).toBeNull();
});

test('recent-only debt remains reachable and history failures can be retried', async () => {
  responses['/api/finance/reimbursements'].people = [];
  client.get.mockImplementation(url => url.endsWith('/history')
    ? Promise.reject(new Error('offline')) : Promise.resolve({ data: responses[url] }));
  await act(async () => root.render(<FinanceView username="actor" />));
  await act(async () => button('К возврату').click());
  expect(container.querySelector('tbody tr').textContent).toContain('Анна Иванова0 ₽200 ₽');
  await act(async () => button('Анна Иванова').click());
  expect(container.querySelector('[role="dialog"] [role="alert"]')).not.toBeNull();
  client.get.mockImplementation(url => Promise.resolve({ data: responses[url] }));
  await act(async () => button('Повторить').click());
  expect(container.querySelectorAll('[role="dialog"] li')).toHaveLength(2);
  await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
  expect(container.querySelector('[role="dialog"]')).toBeNull();
});

test('bank expense locks the payer to the bank and preserves personal payer when switching', async () => {
  await act(async () => root.render(<FinanceView username="actor" isAdmin />));
  await act(async () => button('− Расход').click());
  change('#expense-type', 'Личные траты');
  expect(container.querySelector('#expense-who').value).toBe('Дарья Шарыгина');
  change('#expense-who', 'Анна Иванова');
  change('#expense-type', 'Трата со счета ФоШу');
  expect(container.querySelector('#expense-who').value).toBe('Копилка');
  expect(container.querySelector('#expense-who').readOnly).toBe(true);
  change('#expense-type', 'Личные траты');
  expect(container.querySelector('#expense-who').value).toBe('Анна Иванова');
  change('#expense-type', 'Возврат');
  expect(container.querySelector('label[for="expense-who"]').textContent).toBe('Кому вернули');
  change('#expense-type', 'Трата со счета ФоШу');
  change('form select', 'Театр');
  change('input[type="number"]', '500');
  change('input[placeholder="клининг"]', 'Реквизит');
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(client.post).toHaveBeenCalledWith('/api/finance/expense', expect.objectContaining({
    who: 'Копилка', expense_type: 'Трата со счета ФоШу', amount: '500', project: 'Театр',
  }));
  expect(client.get.mock.calls.filter(([url]) => url.endsWith('/reimbursements'))).toHaveLength(2);
});

test('late identity lookup does not replace a chosen payer or the bank label', async () => {
  let resolveIdentity;
  client.get.mockImplementation(url => url.endsWith('/whoami')
    ? new Promise(resolve => { resolveIdentity = resolve; }) : Promise.resolve({ data: responses[url] }));
  await act(async () => root.render(<FinanceView username="actor" isAdmin />));
  await act(async () => button('− Расход').click());
  change('#expense-who', 'Анна Иванова');
  change('#expense-type', 'Трата со счета ФоШу');
  await act(async () => resolveIdentity({ data: { name: 'Дарья Шарыгина' } }));
  expect(container.querySelector('#expense-who').value).toBe('Копилка');
  change('#expense-type', 'Личные траты');
  expect(container.querySelector('#expense-who').value).toBe('Анна Иванова');
});

test('empty debts are distinguished from a failed request', async () => {
  responses['/api/finance/reimbursements'] = { total: 0, people: [], unassigned: { personal: 0, returned: 0 } };
  await act(async () => root.render(<FinanceView username="actor" isAdmin />));
  await act(async () => button('К возврату').click());
  expect(container.textContent).toContain('Все личные траты компенсированы');
  client.get.mockRejectedValue(new Error('offline'));
  await act(async () => root.render(<FinanceView username="actor" isAdmin dataVersion={1} />));
  expect(container.textContent).not.toContain('Все личные траты компенсированы');
  expect(container.textContent).toContain('Не удалось загрузить суммы к возврату');
});

test('unassigned rows are visible and mark the total as provisional', async () => {
  responses['/api/finance/reimbursements'].unassigned = { personal: 200, returned: 100 };
  responses['/api/finance/reimbursements'].total = 1500;
  await act(async () => root.render(<FinanceView username="actor" isAdmin />));
  await act(async () => button('К возврату').click());
  expect(container.textContent).toContain('Итог предварительный');
  expect(container.textContent).toContain('Без имени: 200 ₽');
  expect(container.textContent).toContain('Возвраты без получателя не вычтены');
});
