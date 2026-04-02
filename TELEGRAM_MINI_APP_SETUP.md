# 🎭 Запуск Telegram Mini App

Ваше приложение теперь встроено в Telegram бота. Вот как это работает:

## 🏗️ Архитектура

```
Telegram Бот
├── /start → показывает кнопку "Открыть приложение"
│   └── Кнопка открывает React приложение внутри Telegram
│       └── Frontend получает user_id от Telegram
│           └── Делает запросы на Backend API
```

## 🚀 Для разработки (ngrok)

ngrok создаёт HTTPS туннель из localhost на интернет. Telegram требует HTTPS для Mini App.

### 1️⃣ Установите ngrok

**macOS:**
```bash
brew install ngrok
```

**Linux/Windows:**
Скачайте с https://ngrok.com/download и добавьте в PATH

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

**Терминал 3 — ngrok:**
```bash
ngrok http 3000  # экспонирует localhost:3000 на интернет
```

Увидите вывод вроде:
```
Session Status                online
Account                       ...
Version                       3.1.0
Region                        ...
Forwarding                    https://abc123xyz.ngrok.io -> http://localhost:3000
```

### 3️⃣ Обновите .env

Скопируйте HTTPS URL (например `https://abc123xyz.ngrok.io`) и поместите в `.env`:

```env
MINI_APP_URL=https://abc123xyz.ngrok.io
```

### 4️⃣ Перезапустите backend

```bash
# Нажмите Ctrl+C в терминале backend
# Затем снова запустите
python main.py
```

В логах должно увидеть:
```
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
3. Railway автоматически создаст dockerfile и разверёт
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

### API запросы

Frontend делает обычные HTTP запросы на backend:
```javascript
client.get('/api/calendar/events?user_id=' + userId)
```

Backend проверяет `user_id` и возвращает данные.

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
- MINI_APP_URL неправильный
- ngrok сессия закончилась (URL меняется каждый раз!)
- Обновите .env и перезапустите backend

**Q: Бот не отвечает на /start**
- BOT_TOKEN неправильный
- Бот не добавлен в .env
- Проверьте логи: `python main.py`

**Q: MINI_APP_URL меняется каждый раз при перезапуске ngrok**
- Это нормально для бесплатного ngrok
- Платный plan даёт постоянный URL
- Для production используйте реальный хостинг (Railway и т.д.)

## 🎯 Чек-лист перед production

- [ ] Google Calendar настроена и синхронизируется
- [ ] Frontend собирается: `npm run build`
- [ ] Backend имеет HTTPS сертификат (Let's Encrypt)
- [ ] Данные пользователя кэшируются/сессии работают
- [ ] Все переменные окружения на production установлены
- [ ] Логи пишутся в файл, а не только в консоль
- [ ] Есть мониторинг/алерты при ошибках
