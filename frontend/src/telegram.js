// Load the SDK after React can render a useful loading/error screen.
let pending;

export function loadTelegram() {
  if (window.Telegram?.WebApp) return Promise.resolve(window.Telegram.WebApp);
  if (pending) return pending;
  pending = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://telegram.org/js/telegram-web-app.js';
    script.async = true;
    const finish = error => {
      clearTimeout(timer);
      script.onload = null;
      script.onerror = null;
      if (error) {
        script.remove();
        reject(error);
      } else {
        resolve(window.Telegram.WebApp);
      }
    };
    const failure = () => finish(new Error('Не удалось подключиться к Telegram. Проверь соединение и нажми «Повторить попытку».'));
    const timer = setTimeout(failure, 8000);
    script.onload = () => window.Telegram?.WebApp ? finish() : failure();
    script.onerror = failure;
    document.head.appendChild(script);
  }).finally(() => { pending = null; });
  return pending;
}
