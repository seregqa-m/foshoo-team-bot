# Foshoo Theatre Bot

Telegram Mini App для управления театральной студией. Бот открывает React-приложение с AI-ассистентом на главной вкладке, расписанием (Google Calendar), опросами посещаемости, финансами и настройками.

## Стек

- **Backend**: FastAPI + aiogram (запускаются в одном процессе)
- **Frontend**: React (Telegram Mini App)
- **БД**: SQLite
- **AI**: YandexGPT 5 Pro через Yandex Cloud Foundation Models (OpenAI-совместимый API)
- **Интеграции**: Google Calendar API, Google Sheets API

## Переменные окружения (`.env`)

```env
# Telegram
BOT_TOKEN=                  # токен от @BotFather
ADMIN_ID=                   # ваш Telegram ID (@userinfobot)
MINI_APP_URL=               # HTTPS URL фронтенда (например https://app.example.com)
GROUP_CHAT_ID=              # ID группы для отправки опросов (отрицательное число)

# Google
GOOGLE_CALENDAR_JSON=backend/credentials.json
GOOGLE_CALENDAR_ID=         # ID календаря Google
GOOGLE_SHEETS_ID=           # ID Google Sheets (маппинг актёров, расписание, финансы)

# Прочее
SYNC_INTERVAL_MINUTES=60
TROUPE_FILTER=труппа 1      # подстрока для фильтрации событий (переопределяется через UI)
SECRET_KEY=                 # секрет для подписи JWT action_token ассистента

# AI-ассистент (YandexGPT)
YANDEX_API_KEY=             # API-ключ сервисного аккаунта, scope yc.ai.languageModels.execute
YANDEX_FOLDER_ID=           # ID каталога Yandex Cloud, начинается с b1g
YANDEX_GPT_MODEL=yandexgpt/latest
ASSISTANT_ENABLED=true
```

## AI-ассистент

Главная вкладка Mini App — свободный чат-интерфейс поверх YandexGPT. Умеет:

- Отвечать на вопросы про данные приложения (баланс, ближайшие события, недавние траты, состав спектакля, активные опросы, кампания занятости) — свежий snapshot автоматически инжектится в промпт, обращения к Sheets кешируются на 60 сек.
- Углубляться через read-tools: `search_expenses`, `get_events_in_range`, `get_show_cast`.
- Выполнять действия через write-tools с обязательным подтверждением: добавить расход/доход, создать/обновить событие, запустить/остановить опрос посещаемости, создать кампанию занятости, пингануть неответивших, изменить глобальные настройки.
- Каждое write-действие проходит через preview-карточку с кнопкой «Выполнить». Токен действия — JWT со сроком жизни 5 мин, подпись `SECRET_KEY`.
- Удаления в реестре tools нет — деструктивные просьбы отклоняются, направляются в UI.
- Аномалии сумм ассистент замечает сам, опираясь на 30-дневную статистику расходов в инжектированном контексте (не хардкод в env).
- Настройки авто-опросов и «текущего спектакля» доступны через иконку ⚙️ в правом верхнем углу вкладки Ассистент — те же поля, что были на прежней вкладке Настройки.

Действия ассистента логируются в таблицу `assistant_action_log` (`user_id`, `tool_name`, args, результат, ошибка, токены).

### Настройка YandexGPT

1. [console.cloud.yandex.ru](https://console.cloud.yandex.ru) → каталог, где будет жить SA
2. В каталоге активировать сервис Yandex Foundation Models
3. IAM → сервисный аккаунт → добавить роль `ai.languageModels.user`
4. Создать API-ключ этого SA. Зона видимости (scope) — `yc.ai.languageModels.execute` (узкая) или `yc.ai.foundationModels.execute` (широкая, если позже добавите SpeechKit)
5. Прописать `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` в `.env`, перезапустить бэкенд

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

## Google Calendar и Sheets

1. Google Cloud Console → создать проект → включить **Google Calendar API** и **Google Sheets API**
2. IAM → Сервисные аккаунты → создать → скачать JSON-ключ
3. Положить файл в `backend/credentials.json`
4. В настройках Google Calendar → поделиться с email сервисного аккаунта (роль: редактор)
5. Google Sheets → поделиться с тем же email сервисного аккаунта
6. Прописать `GOOGLE_CALENDAR_ID` и `GOOGLE_SHEETS_ID` в `.env`

Ожидаемая структура Sheets:
- Вкладка **Труппа** — столбец A: имя, столбец J: telegram username
- Вкладка **Составы спектаклей** — столбец A: название спектакля, B: роль, C: актёр
- Вкладка **График [составы]** — строка 1: заголовки дат, столбец A: имя актёра
- Вкладка **Финансы** — ячейка G4: сумма копилки; именованные таблицы расходов/доходов

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
├── main.py           — точка входа, запускает uvicorn + aiogram polling +
│                       4 фоновых задачи (синк календаря, финансов,
│                       авто-создание опросов, напоминания)
├── bot.py            — обработчики Telegram бота (опросы, доступность)
├── config.py         — конфигурация из .env
├── sheets_client.py  — клиент Google Sheets (маппинг, составы, расписание)
├── finance_router.py — расходы, доходы, копилка
├── links_router.py   — блоки ссылок для вкладки «Ресурсы»
└── modules/
    ├── calendar/     — события, синхронизация с Google Calendar
    ├── polling/      — опросы о посещаемости
    ├── notifications/— настройки уведомлений (через ADMIN_ID строку в БД)
    ├── availability/ — ежемесячные опросы занятости для спектаклей
    ├── finance/      — модели ExpenseLog / IncomeLog / ReturnsLog
    └── assistant/    — AI-ассистент: LLM-обёртка, tools, context builder,
                       confirm-flow, audit log

frontend/src/
├── App.js            — нижняя навигация, четыре вкладки (Ассистент по
│                       умолчанию)
├── api/client.js     — axios + методы ассистента (chat, execute, hints)
└── components/
    ├── AssistantView.js    — чат-интерфейс, landing + chat state,
    │                          ActionPreviewCard, SettingsOverlay (⚙️)
    ├── CalendarView.js     — расписание (WeekCalendar SVG + список)
    ├── PollingView.js      — опросы о посещаемости
    ├── FinanceView.js      — финансы
    ├── LinksView.js        — вкладка «Ресурсы»
    └── NotificationsView.js — контент настроек (открывается из шестерёнки
                               ассистента; отдельной вкладки в tab-bar нет)
```
