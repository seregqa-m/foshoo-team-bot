# 🎭 Запуск Telegram Mini App

Ваше приложение встроено в Telegram бота. Вот как это работает:

## 🏗️ Архитектура

```
Telegram Бот
├── /start → показывает кнопку "Открыть приложение"
│   └── Кнопка открывает React приложение внутри Telegram
│       └── Frontend получает user_id от Telegram
│           └── Делает запросы на Backend API
```

## 🚀 Для разработки (Cloudflare Tunnel)

Telegram требует HTTPS для Mini App. Cloudflare Tunnel создаёт публичный HTTPS туннель из localhost — без регистрации.

### 1️⃣ Установите cloudflared

**macOS:**
```bash
brew install cloudflare/cloudflare/cloudflared
```

**Linux:**
```bash
# Debian/Ubuntu
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb
```

**Windows:**
Скачайте `cloudflared-windows-amd64.exe` с https://github.com/cloudflare/cloudflared/releases

### 2️⃣ Запустите приложение

**Терминал 1 — Frontend:**
```bash
cd frontend
npm install  # если ещё не установлено
npm start    # запустится на http://localhost:3000
```

**Терминал 2 — Backend:**
```bash
cd backend
source venv/bin/activate
python main.py  # запустится на http://127.0.0.1:8000
```

**Терминал 3 — Cloudflare Tunnel:**
```bash
cloudflared tunnel --url localhost:3000
```

Увидите вывод вроде:
```
Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):
https://example-word-word.trycloudflare.com
```

### 3️⃣ Обновите .env

Скопируйте HTTPS URL и поместите в `.env`:

```env
MINI_APP_URL=https://example-word-word.trycloudflare.com
```

### 4️⃣ Перезапустите backend

```bash
# Нажмите Ctrl+C в терминале backend
# Затем снова запустите
python main.py
```

В логах должно появиться:
```
Webhook deleted, starting polling
🤖 Telegram bot started
```

### 5️⃣ Тестируйте в Telegram

1. Откройте Telegram
2. Найдите вашего бота по его username (тот что вы создали у @BotFather)
3. Нажмите /start
4. Должна появиться кнопка **"🎭 Открыть приложение"**
5. Нажмите кнопку → откроется ваше React приложение **внутри Telegram**

## 🚢 Для production (Railway / VPS)

### Вариант 1: Railway (рекомендуется)

1. Создайте аккаунт на https://railway.app
2. Подключите ваш GitHub репо
3. Railway автоматически создаст dockerfile и развернёт
4. Получите URL вроде `https://your-app.railway.app`
5. Обновите в `.env`: `MINI_APP_URL=https://your-app.railway.app`

### Вариант 2: VPS (Hetzner, DigitalOcean)

1. SSH на сервер
2. Клонируйте репо
3. Установите зависимости
4. Используйте systemd или supervisor для фонового запуска
5. Настройте Nginx как reverse proxy с SSL (Let's Encrypt)

## 📋 Как это работает

### Бот (backend/bot.py)

```python
@dp.message(Command("start"))
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🎭 Открыть приложение",
            web_app=WebAppInfo(url=MINI_APP_URL)  # ← ссылка на React
        )
    ]])
    await message.answer("Нажми кнопку...", reply_markup=kb)
```

### Frontend (App.js)

```javascript
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.ready();  // сообщить Telegram что готовы
    const user = tg.initDataUnsafe?.user;  // получить user_id
    setUserId(user.id);
}
```

## 🔐 Безопасность

**Важно:** Telegram передаёт `initData` строку, которая подписана. Для production используйте её для проверки, что запрос действительно от Telegram:

```python
# backend/core/security.py
def verify_initData(initData: str) -> bool:
    # Проверить подпись используя BOT_TOKEN
    # ...
```

Сейчас для разработки это не критично, но на production нужна.

## 🐛 Проблемы

**Q: "Cannot GET /api/calendar/events"**
- Backend выключен или на другом порту
- Проверьте что `python main.py` работает

**Q: "404 Not Found" при нажатии кнопки**
- MINI_APP_URL неправильный или туннель перезапустился (URL меняется!)
- Обновите `.env` и перезапустите backend

**Q: Бот не отвечает на /start**
- Проверьте BOT_TOKEN в `.env`
- Проверьте логи backend: `python main.py`
- Возможен webhook конфликт — проверьте:
  ```
  curl https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo
  ```
  Если `url` не пустой — удалите webhook вручную или просто перезапустите backend (он удаляет его автоматически при старте).

**Q: MINI_APP_URL меняется при перезапуске туннеля**
- Это нормально для бесплатного quick tunnel (`trycloudflare.com`)
- При каждом рестарте `cloudflared` нужно обновлять `.env` и перезапускать backend
- Для постоянного URL: зарегистрируйтесь на Cloudflare и создайте именованный туннель (`cloudflared tunnel create`)

## 🎯 Чек-лист перед production

- [ ] Google Calendar настроена и синхронизируется
- [ ] Frontend собран с правильным `REACT_APP_API_URL`: `REACT_APP_API_URL=https://your-backend npm run build`
- [ ] Backend имеет HTTPS сертификат (Let's Encrypt)
- [ ] Все переменные окружения на production установлены
- [ ] Логи пишутся в файл, а не только в консоль
