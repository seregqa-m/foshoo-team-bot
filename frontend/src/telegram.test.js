import { loadTelegram } from './telegram';

beforeEach(() => { jest.useFakeTimers(); delete window.Telegram; });
afterEach(() => {
  document.querySelectorAll('script[src*="telegram.org"]').forEach(script => script.remove());
  delete window.Telegram;
  jest.useRealTimers();
});

test('concurrent callers share a load and wait for the SDK before continuing', async () => {
  const first = loadTelegram();
  const second = loadTelegram();
  expect(first).toBe(second);
  expect(document.querySelectorAll('script[src*="telegram.org"]')).toHaveLength(1);
  window.Telegram = { WebApp: { initData: 'signed' } };
  document.querySelector('script[src*="telegram.org"]').dispatchEvent(new Event('load'));
  expect(await first).toBe(window.Telegram.WebApp);
  expect(await loadTelegram()).toBe(window.Telegram.WebApp);
});

test('stalled SDK times out and a fresh attempt can succeed', async () => {
  const failed = expect(loadTelegram()).rejects.toThrow('Не удалось подключиться к Telegram');
  jest.advanceTimersByTime(8000);
  await failed;
  expect(document.querySelector('script[src*="telegram.org"]')).toBeNull();
  const retry = loadTelegram();
  window.Telegram = { WebApp: {} };
  document.querySelector('script[src*="telegram.org"]').dispatchEvent(new Event('load'));
  expect(await retry).toBe(window.Telegram.WebApp);
});

test('SDK network error fails promptly', async () => {
  const failed = expect(loadTelegram()).rejects.toThrow('Не удалось подключиться к Telegram');
  document.querySelector('script[src*="telegram.org"]').dispatchEvent(new Event('error'));
  await failed;
});
