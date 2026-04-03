# ⚡ Быстрый Старт

## Локально (рекомендуется для разработки)

> **Важно:** Приложение теперь встроено в Telegram бота! Чтобы тестировать в Telegram, нужен **ngrok** для HTTPS туннеля (см. ниже).

### 1️⃣ Подготовка

```bash
# Создайте .env файл
cp .env.example .env

# Отредактируйте .env и вставьте:
# - BOT_TOKEN (получить у @BotFather)
# - ADMIN_ID (узнать у @userinfobot)
```

### 2️⃣ Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Запустите (откройте этот терминал, не закрывайте)
python main.py
```

### 3️⃣ Frontend

```bash
# В новом терминале
cd frontend
npm install
npm start
```

✅ Backend: http://127.0.0.1:8000
✅ Frontend: http://127.0.0.1:3000

### 4️⃣ Cloudflare Tunnel для HTTPS (обязательно для Telegram Mini App)

**Новый терминал:**
```bash
cloudflared tunnel --url localhost:3000
```

Скопируйте HTTPS URL (вроде `https://example-word-word.trycloudflare.com`), вставьте в `.env`:
```env
MINI_APP_URL=https://example-word-word.trycloudflare.com
```

Перезапустите backend (Ctrl+C и `python main.py` заново).

Установка cloudflared: `brew install cloudflare/cloudflare/cloudflared` (macOS) или скачайте с https://github.com/cloudflare/cloudflared/releases

### 5️⃣ Тестирование

**В Telegram:**
1. Найдите вашего бота (username который создали у @BotFather)
2. Отправьте `/start`
3. Должна появиться кнопка "🎭 Открыть приложение"
4. Нажмите кнопку → откроется ваше приложение **внутри Telegram**

## Docker (вся система в одной команде)

```bash
# Убедитесь что Docker установлен и .env заполнен
docker-compose up

# Стоп
docker-compose down

# Пересобрать образы
docker-compose up --build
```

✅ Backend: http://localhost:8000
✅ Frontend: http://localhost:3000

## Важно знать

**Telegram Mini App требует HTTPS!**
- Локально используйте Cloudflare Tunnel (`cloudflared tunnel --url localhost:3000`)
- На production (Railway, VPS) — автоматический HTTPS
- URL туннеля меняется при каждом перезапуске → нужно обновлять `MINI_APP_URL` в `.env` и перезапускать backend
- Для постоянного URL: `cloudflared tunnel create <name>` (требует аккаунт на Cloudflare)

**Frontend API URL запекается при сборке (`npm run build`)**
- Если фронт собирался без `REACT_APP_API_URL`, он обращается к `http://127.0.0.1:8000`
- Пользователи с телефонов не смогут достучаться до вашего localhost
- Для production сборки задайте переменную перед `npm run build`:
  ```bash
  REACT_APP_API_URL=https://your-backend-url.com npm run build
  ```
- В dev режиме (`npm start`) это не нужно — браузер обращается к localhost напрямую

**Уведомления хранятся, но не отправляются**
- Модуль `notifications` сохраняет настройки пользователей, но фоновая задача рассылки ещё не реализована
- Кнопка "Уведомления" в приложении работает только для сохранения настроек

## Что дальше?

### Полная инструкция по Telegram Mini App

Читайте `TELEGRAM_MINI_APP_SETUP.md` для деталей по ngrok и production deployment.

### Добавить Google Calendar

1. Google Cloud Console → Создать проект
2. Enable Google Calendar API
3. Скачать credentials.json → поместить в `backend/`
4. Реализовать синхронизацию в `backend/modules/calendar/services.py`

### Добавить новый модуль

```python
# 1. Создайте backend/modules/my_feature/
# 2. Добавьте models.py, services.py, router.py
# 3. Зарегистрируйте router в backend/main.py
# 4. Создайте компонент в frontend/src/components/
```

### Развернуть в сеть

**Railway** (самый простой):
```bash
git push  # автоматическое развертывание
```

**VPS**:
```bash
# SSH на сервер
ssh user@your.server.com

# Клонируйте проект
git clone <repo>
cd theater-bot

# Запустите через supervisor
```

## Структура

```
backend/           — Python API и логика
├── main.py       — Entry point
├── modules/      — Календарь, опросы, уведомления
└── core/         — БД, безопасность

frontend/          — React приложение
├── src/
│   ├── App.js
│   └── components/  — Календарь, опросы, уведомления
└── public/         — Static файлы
```

## FAQ

**Q: Не работает бот (не отвечает на /start)**
- Проверьте BOT_TOKEN в .env
- Убедитесь что backend запущен: `curl http://127.0.0.1:8000`
- Проверьте, нет ли активного webhook (он блокирует long polling):
  ```
  curl https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo
  ```
  Если поле `url` не пустое — удалите webhook:
  ```
  curl -X POST https://api.telegram.org/bot<BOT_TOKEN>/deleteWebhook
  ```
  Затем перезапустите backend. При старте приложение теперь делает это автоматически.
- Смотрите логи backend — ошибки бота выводятся туда

**Q: Не работает frontend**
- npm install прошла успешно? Есть node_modules/
- Port 3000 свободен? sudo lsof -i :3000

**Q: Как обновить зависимости**
```bash
# Backend
pip install --upgrade -r requirements.txt

# Frontend
npm update
```

**Q: Где логи?**
- Backend: консоль где запустили python main.py
- Frontend: DevTools браузера (F12)
- Docker: docker-compose logs -f backend
