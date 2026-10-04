# AGENTS.md

## Обязательное правило: не использовать Стефанию

В проекте `foshoo` — в `/Users/seregqa/Documents/claude/foshoo-bot` и всех его
подкаталогах — **НИКОГДА НЕ ИСПОЛЬЗОВАТЬ СТЕФАНИЮ (STEFANIA)**.

- Работать как обычный Codex, без роли, персоны и рабочих процедур Стефании.
- Не запускать и не применять никакие навыки `stefania-*` и
  `source-command-stefania-*`, включая память, базу знаний и регистрацию ошибок.
- Не читать и не обновлять `~/.stefania/`, память и базу знаний Стефании;
  не подключать её настройки, хуки или автоматизации для этого проекта.
- Контекст проекта восстанавливать из текущего диалога, файлов репозитория
  и истории Git, без обращения к Стефании.
- Это явное правило пользователя для проекта имеет приоритет над общими
  пользовательскими инструкциями Стефании, в том числе автоматически
  добавленным блоком `stefania-core` и унаследованными пользовательскими
  инструкциями из родительских каталогов.

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Theater Studio Telegram Mini App — a management tool for a theater studio. Users interact via a Telegram bot that opens a React-based Mini App. The backend runs FastAPI + aiogram simultaneously in one process.

## Development Commands

### Backend

**Python — только из отдельного virtualenv проекта.** Это явное требование
пользователя. Запуск backend, тестов, скриптов и установка зависимостей должны
использовать интерпретатор выбранного окружения по явному пути и его
`python -m pip`. Не использовать системный `/usr/bin/python3`, не подменять
окружение произвольным `python`/`python3` из PATH и не устанавливать зависимости
глобально.

Перед запуском определить существующее рабочее окружение проекта и проверить
версию именно его интерпретатора (для текущего кода нужен Python 3.10+).
Версия системного Python не показывает версию проектного окружения.
Не считать любой найденный `venv/` подходящим без проверки и не пересоздавать
существующее окружение автоматически. Если путь к рабочему env неизвестен или
его запуск заблокирован, уточнить путь/сообщить о блокировке; не переходить
на системный Python.

Рабочее окружение с 4 октября 2026: `.venv` на Python **3.11.15**.
Использовать `/Users/seregqa/Documents/claude/foshoo-bot/.venv/bin/python`
(из `backend/` — `../.venv/bin/python`), включая установку тестовых зависимостей
через `-m pip install -r backend/requirements-dev.txt`. Проверены версия,
принадлежность virtualenv (`sys.prefix != sys.base_prefix`) и загрузка Expat.

Старый `venv` на Python 3.9.6 сохранён без изменений; для текущего кода не подходит.
После переоткрытия проекта в обычном редакторе VS Code команды Git, Node/npm
и Python стали доступны. Однако Homebrew Python 3.11.15 не смог создать рабочий
env из-за несовместимости с системной Expat
(`Symbol not found: _XML_SetAllocTrackerActivationThreshold`). Поэтому `.venv`
создан на автономном CPython 3.11.15, загруженном установленным `uv` в
`.venv/runtime/cpython-3.11.15-macos-aarch64-none`. Этот runtime — часть окружения;
не удалять его отдельно. Homebrew и системные библиотеки не изменялись.

Команды ниже выполняются из `backend/`; `PROJECT_ENV_PYTHON` должен содержать
абсолютный путь к Python проверенного проектного virtualenv:

```bash
cd backend
PROJECT_ENV_PYTHON=/Users/seregqa/Documents/claude/foshoo-bot/.venv/bin/python
"$PROJECT_ENV_PYTHON" --version
"$PROJECT_ENV_PYTHON" -m pip install -r requirements.txt
cp ../.env.example .env  # then fill in BOT_TOKEN etc.
"$PROJECT_ENV_PYTHON" main.py  # starts uvicorn + aiogram polling together
"$PROJECT_ENV_PYTHON" -B -m unittest discover -s tests
```

### Frontend

```bash
cd frontend
npm install
npm start   # dev server on :3000
npm run build   # production build
```

### Docker (full stack)

```bash
cp .env.example .env  # fill in BOT_TOKEN, ADMIN_ID
docker-compose up
```

## Architecture

### Process model

`backend/main.py` is the single entry point. On FastAPI startup it launches four asyncio tasks:
- `dp.start_polling(bot)` — aiogram Telegram bot
- `sync_calendar_background()` — periodic Google Calendar sync (every `SYNC_INTERVAL_MINUTES`)
- `sync_finance_background()` — periodic Google Sheets → DB finance sync (every `SYNC_INTERVAL_MINUTES`)
- `poll_reminder_background()` — checks every minute: auto-create polls N days before events, send reminder + pin poll 1 day before event

### Module structure

Each feature lives in `backend/modules/<name>/` with the same four files:
- `models.py` — SQLAlchemy models (must import `Base` from `core.database`)
- `services.py` — business logic (takes `db: Session` in `__init__`)
- `router.py` — FastAPI `APIRouter` with prefix `/api/<name>`
- `__init__.py`

Modules: `calendar`, `polling`, `notifications`, `availability`.

To add a module: create the four files, then `app.include_router(...)` in `main.py`.

### Database

SQLite in development (`theater_bot.db` in `backend/`). `core/database.py` exposes:
- `Base` — declarative base for all models
- `get_db()` — FastAPI dependency (yields `Session`)
- `init_db()` — called at startup to `create_all`

### Frontend

Single-page React app (`frontend/src/App.js`) with four tab views: `CalendarView`, `PollingView`, `FinanceView`, `NotificationsView` (labelled "Настройки" with ⚙️ icon). Telegram user ID is extracted from `window.Telegram.WebApp.initDataUnsafe.user` on mount and passed as `userId` prop to each view.

`App.js` also fetches `/api/auth/app-config` on mount to get `trouFilter` (the configurable troupe name filter string) and passes it as a prop to `CalendarView`.

All API calls go through `frontend/src/api/client.js` (axios instance). API base URL is configured via `REACT_APP_API_URL` env var (defaults to `http://127.0.0.1:8000`).

### Key configuration

All config is read from `.env` via `backend/config.py`. `BOT_TOKEN` is required — the app crashes on startup without it. For local dev, `MINI_APP_URL` should be set to a Cloudflare Tunnel URL: `cloudflared tunnel --url localhost:3000`. The URL changes on every restart — update `.env` and restart the backend each time.

Key env vars beyond BOT_TOKEN:
- `GOOGLE_CALENDAR_JSON` — path to service account JSON (default: `backend/credentials.json`)
- `GOOGLE_CALENDAR_ID` — calendar ID for sync
- `GOOGLE_SHEETS_ID` — spreadsheet ID for actor mapping, schedules, finances
- `GROUP_CHAT_ID` — Telegram group where polls are sent
- `ADMIN_ID` — Telegram user ID of admin; the `notification_settings` row for this user acts as global app config
- `TROUPE_FILTER` — default troupe name substring filter (default: `"труппа 1"`); can be overridden per-session via the Settings UI (stored in `notification_settings.troupe_filter`)
- `SYNC_INTERVAL_MINUTES` — calendar/finance background sync interval

Google Calendar integration requires `backend/credentials.json` (OAuth2 service account) and `GOOGLE_CALENDAR_ID` set in `.env`. If the credentials file is absent, sync is silently skipped. All-day events (Google returns `date` field, not `dateTime`) are handled via `CalendarService._parse_dt()`.

Calendar sync (`sync_from_google`) tracks which event IDs were returned by Google and marks any DB events not in the response as `is_cancelled=True`. Associated active polls are deactivated at the same time.

### Availability campaigns

The "Опрос занятости" feature (`modules/availability/`) lets admins run a monthly availability survey:
1. Admin picks shows and upcoming calendar dates → `POST /api/availability/campaign`
2. Backend sends Telegram native multi-answer polls (batched in groups of 10, Telegram's limit)
3. `bot.py` routes `poll_answer` updates: regular polls → existing logic; availability polls → `_handle_availability_answer()` which writes "да"/"нет" per option to Google Sheets "График [составы]"
4. Admin can view non-voters (`GET /api/availability/non-voters`) and ping them (`POST /api/availability/ping-non-voters`)
5. Only the latest campaign is kept — creating a new one deletes the old one

Non-voter detection cross-references `AvailabilityVote` table against actor cast lists from the "Составы спектаклей" sheet tab.

### Poll auto-creation and reminders

`poll_reminder_background()` runs every 60 seconds and calls three functions:

1. **`_cleanup_old_polls()`** — deletes polls whose event ended more than 1 day ago
2. **`_auto_create_polls()`** — if `poll_reminders_enabled` is on and current Moscow time ≥ `reminder_time`, finds events on `now + reminder_days_before` days, skips shows and non-`TROUPE_FILTER` events, creates poll via `PollingService` + `bot.send_poll()`
3. **`_send_poll_reminders()`** — 1 day before each event, resolves its show from the calendar title and tags that show's cast members who haven't voted (all actors for events without a recognized show), then pins the poll message. The legacy `current_show` column is retained for database compatibility and is no longer used.

### Known gaps

- **Notification dispatcher legacy** — `NotificationService` still stores `Notification` rows but the actual dispatch is handled by `poll_reminder_background()`, not a notification service. The old rows are unused.
- **user_id is an unauthenticated query param** — polls and notification endpoints accept `?user_id=N` without JWT/HMAC verification. Acceptable for an internal admin tool but not for public use.
- **Frontend API URL is baked at build time** — `REACT_APP_API_URL` must be set before `npm run build` for production. Dev server (`npm start`) uses `127.0.0.1:8000` by default.

### Bot + uvicorn coexistence

At startup `main.py` deletes any active Telegram webhook (`bot.delete_webhook`) then starts aiogram polling as a background asyncio task with `handle_signals=False` to avoid conflicting with uvicorn's SIGTERM handler. If polling fails (bad token, conflict), the error is logged and the HTTP API continues running.
