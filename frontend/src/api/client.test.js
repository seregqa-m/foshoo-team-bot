import client, { DATA_CHANGED_EVENT } from './client';

beforeEach(() => {
  window.Telegram = { WebApp: { initData: 'signed-test-data' } };
  client.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: {} });
});
afterEach(() => { delete window.Telegram; });

test('all API requests carry signed initData', async () => {
  const response = await client.get('/api/calendar/events');
  expect(response.config.headers.get('X-Telegram-Init-Data')).toBe('signed-test-data');
});

test('successful writes invalidate data; chat requests do not', async () => {
  const listener = jest.fn();
  window.addEventListener(DATA_CHANGED_EVENT, listener);
  await client.post('/api/assistant/chat', {});
  expect(listener).not.toHaveBeenCalled();
  await client.post('/api/finance/expense', {});
  expect(listener).toHaveBeenCalledTimes(1);
  window.removeEventListener(DATA_CHANGED_EVENT, listener);
});

test('reviewing a draft does not trigger a global reload loop, while real writes still refresh data', async () => {
  const changed = jest.fn();
  window.addEventListener(DATA_CHANGED_EVENT, changed);
  try {
    await client.post('/api/planning/repertoire/draft', {});
    expect(changed).not.toHaveBeenCalled();
    await client.put('/api/planning/repertoire', {});
    expect(changed).toHaveBeenCalledTimes(1);
  } finally { window.removeEventListener(DATA_CHANGED_EVENT, changed); }
});
