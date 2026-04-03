# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Theater Studio Telegram Mini App — a management tool for a theater studio. Users interact via a Telegram bot that opens a React-based Mini App. The backend runs FastAPI + aiogram simultaneously in one process.

## Development Commands

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env  # then fill in BOT_TOKEN etc.
python main.py            # starts uvicorn + aiogram polling together
```

### Frontend

```bash
cd frontend
npm install
npm start   # dev server on :3000
npm build   # production build
```

### Docker (full stack)

```bash
cp .env.example .env  # fill in BOT_TOKEN, ADMIN_ID
docker-compose up
```

## Architecture

### Process model

`backend/main.py` is the single entry point. On FastAPI startup it launches two asyncio tasks:
- `dp.start_polling(bot)` — aiogram Telegram bot
- `sync_calendar_background()` — periodic Google Calendar sync (every `SYNC_INTERVAL_MINUTES`)

### Module structure

Each feature lives in `backend/modules/<name>/` with the same four files:
- `models.py` — SQLAlchemy models (must import `Base` from `core.database`)
- `services.py` — business logic (takes `db: Session` in `__init__`)
- `router.py` — FastAPI `APIRouter` with prefix `/api/<name>`
- `__init__.py`

To add a module: create the four files, then `app.include_router(...)` in `main.py`.

### Database

SQLite in development (`theater_bot.db` in `backend/`). `core/database.py` exposes:
- `Base` — declarative base for all models
- `get_db()` — FastAPI dependency (yields `Session`)
- `init_db()` — called at startup to `create_all`

### Frontend

Single-page React app (`frontend/src/App.js`) with three tab views: `CalendarView`, `PollingView`, `NotificationsView`. Telegram user ID is extracted from `window.Telegram.WebApp.initDataUnsafe.user` on mount and passed as `userId` prop to each view.

All API calls go through `frontend/src/api/client.js` (axios instance). API base URL is configured via `REACT_APP_API_URL` env var (defaults to `http://127.0.0.1:8000`).

### Key configuration

All config is read from `.env` via `backend/config.py`. `BOT_TOKEN` is required — the app crashes on startup without it. For local dev, `MINI_APP_URL` should be set to a Cloudflare Tunnel URL: `cloudflared tunnel --url localhost:3000`. The URL changes on every restart — update `.env` and restart the backend each time.

Google Calendar integration requires `backend/credentials.json` (OAuth2 service account) and `GOOGLE_CALENDAR_ID` set in `.env`. If the credentials file is absent, sync is silently skipped. All-day events (Google returns `date` field, not `dateTime`) are handled via `CalendarService._parse_dt()`.

### Known gaps

- **Notification dispatcher not implemented** — `NotificationService` stores settings and creates `Notification` rows, but there is no background loop that reads pending notifications and dispatches them via the Telegram bot. The "Уведомления" tab is UI-only.
- **user_id is an unauthenticated query param** — polls and notification endpoints accept `?user_id=N` without JWT/HMAC verification. Acceptable for an internal admin tool but not for public use.
- **Frontend API URL is baked at build time** — `REACT_APP_API_URL` must be set before `npm run build` for production. Dev server (`npm start`) uses `127.0.0.1:8000` by default.

### Bot + uvicorn coexistence

At startup `main.py` deletes any active Telegram webhook (`bot.delete_webhook`) then starts aiogram polling as a background asyncio task with `handle_signals=False` to avoid conflicting with uvicorn's SIGTERM handler. If polling fails (bad token, conflict), the error is logged and the HTTP API continues running.
