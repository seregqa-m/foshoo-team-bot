# Foshoo Theatre Bot

Telegram Mini App для управления театральной студией. Бот открывает React-приложение с расписанием (Google Calendar), опросами о посещаемости и настройками уведомлений.

## Стек

- **Backend**: FastAPI + aiogram (запускаются в одном процессе)
- **Frontend**: React (Telegram Mini App)
- **БД**: SQLite
- **Интеграция**: Google Calendar API

## Переменные окружения (`.env`)

```env
BOT_TOKEN=                  # токен от @BotFather
ADMIN_ID=                   # ваш Telegram ID (@userinfobot)
MINI_APP_URL=               # HTTPS URL фронтенда (например https://app.example.com)
GOOGLE_CALENDAR_JSON=backend/credentials.json
GOOGLE_CALENDAR_ID=         # ID календаря Google
GROUP_CHAT_ID=              # ID группы для отправки опросов (отрицательное число)
SYNC_INTERVAL_MINUTES=60
```

## Запуск на сервере (production)

```bash
# Backend
cd /путь/к/проекту
source venv/bin/activate
cd backend && python main.py

# Frontend — собрать один раз
cd frontend
REACT_APP_API_URL=https://ваш-домен.com npm run build
# Статика раздаётся через nginx из папки frontend/build/
```

### Пример nginx конфига

```nginx
server {
    server_name ваш-домен.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        root /путь/к/frontend/build;
        try_files $uri $uri/ /index.html;
    }

    listen 443 ssl;
    # ssl_certificate ...
}
```

## Google Calendar

1. Google Cloud Console → создать проект → включить **Google Calendar API**
2. IAM → Сервисные аккаунты → создать → скачать JSON-ключ
3. Положить файл в `backend/credentials.json`
4. В настройках Google Calendar → поделиться с email сервисного аккаунта (роль: редактор)
5. Прописать `GOOGLE_CALENDAR_ID` в `.env`

## Локальная разработка

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py

# Frontend
cd frontend
npm install
REACT_APP_API_URL=http://127.0.0.1:8000 npm start
```

Для тестирования Mini App локально нужен HTTPS-туннель:
```bash
cloudflared tunnel --url localhost:3000
# Скопируйте URL в MINI_APP_URL в .env и перезапустите backend
```

## Архитектура

```
backend/
├── main.py           — точка входа, запускает uvicorn + aiogram polling
├── bot.py            — обработчики Telegram бота
├── config.py         — конфигурация из .env
└── modules/
    ├── calendar/     — события, синхронизация с Google Calendar
    ├── polling/      — опросы о посещаемости
    └── notifications/— настройки уведомлений (отправка не реализована)

frontend/src/
├── App.js            — нижняя навигация, три вкладки
└── components/
    ├── CalendarView.js
    ├── PollingView.js
    └── NotificationsView.js
```
