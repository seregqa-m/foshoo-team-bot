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

`backend/main.py` is the single entry point. Outside recovery, FastAPI startup launches:
- `dp.start_polling(bot)` — aiogram Telegram bot
- `sync_calendar_background()` — periodic Google Calendar sync (every `SYNC_INTERVAL_MINUTES`)
- `sync_finance_background()` — periodic Google Sheets → DB finance sync (every `SYNC_INTERVAL_MINUTES`)
- `attendance_sync_background()` — verify pending voter memberships and retry registration/attendance export every minute, even with poll automation disabled
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

Single-page React app (`frontend/src/App.js`) with calendar, finance, resources
and (when enabled and authorized) assistant tabs. Settings (`NotificationsView`)
open from the assistant; there is no separate settings tab. Admins manage monthly
polls in `AvailabilitySection` inside `PlanningView`, below the cast summary.
The authenticated user ID comes from `/api/auth/check` and is passed to views.

`App.js` fetches `/api/auth/app-config` for assistant availability. Calendar types,
canonical show names and stable show IDs come from `/api/calendar/events`.
Rehearsal filters and colors use the show ID; all performances share green.
The hue sequence uses disjoint identities: show N maps to index 2N-1,
recurring group N to 2N. Never feed bare IDs from the two tables into the
same color formula; names and the visible event set do not affect colors.
Other events use persistent title groups (`calendar_color_groups` and
`calendar_color_titles`), colored only after three distinct dates within the
rolling -90/+60-day window. Normalization and conservative Levenshtein matching
(>=90%, <=2 edits, complete-link, ambiguity separated) recognize variants.
Short titles, numbers and workshop teacher names are protected. These groups
use the same saturation/lightness as catalog rehearsals; rare events, rental and cleaning stay gray. Lab events follow
the same recurrence rule. Grouping never changes classification or poll routing.
Primary calendar filters are only All/Rehearsals/Performances/Other, derived
from the same ongoing/upcoming events as the list, excluding history. Names
are secondary dropdown choices with counts within the selected type; Other
includes recurring groups. Missing selections reset to All/all names. The
week grid retains full history and past-event opacity. Filter selection is
explicitly dark; cards show text type labels. External performances can use
`[Спект]` without a catalog entry or chat; catalog chat IDs are optional.

All API calls go through `frontend/src/api/client.js` (axios instance). API base URL is configured via `REACT_APP_API_URL` env var (defaults to `http://127.0.0.1:8000`).

### Key configuration

All config is read from `.env` via `backend/config.py`. `BOT_TOKEN` is required — the app crashes on startup without it. For local dev, `MINI_APP_URL` should be set to a Cloudflare Tunnel URL: `cloudflared tunnel --url localhost:3000`. The URL changes on every restart — update `.env` and restart the backend each time.

Key env vars beyond BOT_TOKEN:
- `GOOGLE_CALENDAR_JSON` — path to service account JSON (default: `backend/credentials.json`)
- `GOOGLE_CALENDAR_ID` — calendar ID for sync
- `GOOGLE_SHEETS_ID` — spreadsheet ID for actor mapping, schedules, finances
- `GROUP_CHAT_ID` — legacy group for application access/admin checks and migration of old publications; new poll destinations come from `theater_shows.telegram_chat_id`
- `ADMIN_ID` — Telegram user ID of admin; the `notification_settings` row for this user acts as global app config
- `SYNC_INTERVAL_MINUTES` — calendar/finance background sync interval

Google Calendar integration requires `backend/credentials.json` (OAuth2 service account) and `GOOGLE_CALENDAR_ID` set in `.env`. If the credentials file is absent, sync is silently skipped. All-day events (Google returns `date` field, not `dateTime`) are handled via `CalendarService._parse_dt()`.

Calendar sync (`sync_from_google`) tracks which event IDs were returned by Google and marks any DB events not in the response as `is_cancelled=True`. Associated active polls are deactivated at the same time.

### Shared attendance and multi-chat polls

The confirmed key for availability is **(Telegram user_id, local calendar date)**, never show, chat or time slot. Both regular and monthly polls update `modules/attendance/`. The latest changed answer for each date wins. Duplicate delivery and unchanged dates in a multi-answer poll do not overwrite newer answers elsewhere. Retraction clears only the currently authoritative source; it never revives an older vote.

`DayAnswer` is the current answer, `AnswerSource` deduplicates per-publication payloads, `AnswerHistory` retains accepted changes, and `PollUpdate` deduplicates Telegram updates. Regular polls and availability options freeze their dates. A moved event needs new-day answers; a different show on the same date uses existing answers. Preserve these invariants.

The existing cast planner merges the common answers into Sheets data and includes every show in the theater catalog, retaining legacy Sheets shows. Unknown casts remain incomplete. Roles are still maintained in Sheets; attendance export must never overwrite a role cell. Planner assignment and export share `answer_lock`. Export failures retain the committed answer and are retried by the background worker. Once a common answer exists, a manual yes/no edit in Sheets does not override it.

Availability campaigns publish one copy per distinct mapped chat, with up to 9 dates plus «Ни одна из дат». Selecting that option alone means no on every date; when combined with dates, explicit selected dates win. Unselected dates become no only after that part is answered. Campaign history is retained. Same dates/destinations reuse existing publications; confirmed delivery failures can retry without duplicating success. An unconfirmed send requires explicit checking of the chat before retry. A bot-triggered campaign is scoped to shows mapped to that chat and requires its admin or a superadmin.

New sends resolve the show through `modules/theater/routing.py`, using the catalog and saved aliases. For missing or ambiguous show names, the calendar poll endpoint returns `409` with `detail.code=show_required` and catalog choices. The event card lets an admin select a show and retry with `{show_id}`. Selection is stored in `calendar_events.poll_show_id` plus a title snapshot (`poll_show_title`); it survives calendar sync and drives reminders, but is ignored after a title change. Revalidate the current mapping before sending. Missing chat remains an error, with no `GROUP_CHAT_ID` fallback. Calendar rehearsal titles can include the show and `[Реп]`, e.g. `Урод [Реп]`. Pin/stop/link operations always use the publication's stored chat. New reminders use the current mapping and verified registered chat participants, excluding anyone who answered that date in either poll type or another chat.

`poll_reminder_background()` archives old polls, publishes configured rehearsals within the configured days-before window (retrying missed sends), and sends next-day reminders. It respects `poll_reminders_enabled` and `reminder_time`. An explicitly stopped poll is not reopened by the automatic job. The legacy `current_show` column remains unused.

Calendar types also accept standalone `Реп` / `Репетиция` or `Спект` / `Спектакль`
outside brackets, e.g. `Репетиция [Цианистый Калий]`. Existing `[Реп]` / `[Спект]`
tags retain precedence. Show matching preserves bracketed names (square or round)
and excludes only type-only tags; routing and classification share this parsing.
A known show name without an explicit type remains a performance. The calendar API
resolves show identities through the theater catalog and saved aliases. Monthly
attendance dates are selected by rehearsal type without needing a Sheets read.
Attendance eligibility depends only on the rehearsal type, with no legacy group
substring matching. Manual event polls enforce the same rule as automatic jobs.
Unknown types appear under «Прочее»; rehearsals without a resolved show remain
available for manual show selection. Obsolete DB columns can remain in existing
databases without being mapped, read or migrated into fresh databases.

Identified votes in regular/monthly polls of connected groups enqueue `attendance_voters` registrations. A separate worker verifies Telegram membership before enrolling the person in Sheets. The `Труппа` sheet retains A=name and J=username; a dynamically located/added `Telegram ID` column binds identity across username changes and missing usernames. Only a unique unclaimed legacy username can link a previous row; matching names never imply identity. Ambiguous IDs/usernames are deferred for manual repair. Registration writes and attendance export share `answer_lock`; RAW writes preserve other columns and assigned roles. Re-reading both sheets makes retries after a lost write response idempotent under the single-worker deployment; concurrent human sheet edits are not transactionally locked. Roles/casts are not inferred from chat membership. Failed external operations retain committed votes.

Startup migrations preserve old publications, backfill their chat from `GROUP_CHAT_ID` and snapshot their current event date once. No source rows or existing Sheets answers are deleted. Legacy availability votes lack option choices, so do not invent historical yes/no answers from their mere presence.

Application access also accepts current membership in any mapped chat, checked on every request without a cached group allow. Existing superadmin/legacy group-admin/legacy Sheets access is preserved. `attendance_voters.legacy_access` records the previous Sheets grant before first automatic sheet writes; auto-created rows never grant permanent or financial access. Finance and assistant routes require legacy/admin access, with `can_finance` controlling the frontend. Group administration never implies global administration except the existing `GROUP_CHAT_ID` rule.

`attendance_chat_participants` stores independent `(chat_id, user_id)` memberships, verification timestamps and revision. Votes and `chat_member` updates populate it; known people are rechecked every five minutes. All registered current chat members participate in attendance counts. Reminders recheck the target chat before sending and use escaped ID mentions, excluding common-date respondents. No Sheets cast is required for reminders. Theater settings expose a read-only member list; there is no participation toggle or manual exclusion. Planning adds registered-participant totals (yes/no/unknown/unanswered), while role-based assignment requirements remain intact. Migration backfills known IDs from stored votes without inventing availability answers.

The monthly non-voter view also compares the campaign's Sheets casts with the
verified roster. Expected cast members without registration or verified membership
appear separately in `unregistered_participants`, always with `can_ping=false`.
Sheet names join casts to troupe rows only; Telegram identity requires a stable ID
or a unique unclaimed username. These entries do not grant access, create attendance
answers, or become reminder recipients. Sheets read failure exposes `roster_warning`
instead of silently claiming the roster is complete.

### Known gaps

- **Notification dispatcher legacy** — `NotificationService` still stores `Notification` rows but the actual dispatch is handled by `poll_reminder_background()`, not a notification service. The old rows are unused.
- **Telegram identity** — all API routers require signed Telegram initData; any supplied `user_id` must match the authenticated identity. Poll/calendar/settings writes require admin access.
- **Frontend API URL is baked at build time** — `REACT_APP_API_URL` must be set before `npm run build` for production. Dev server (`npm start`) uses `127.0.0.1:8000` by default.

### Bot + uvicorn coexistence

At startup `main.py` deletes any active Telegram webhook (`bot.delete_webhook`) then starts aiogram polling as a background asyncio task with `handle_signals=False` to avoid conflicting with uvicorn's SIGTERM handler. If polling fails (bad token, conflict), the error is logged and the HTTP API continues running.

### Selectel migration and LLM pause (14 October 2026)

- The redesign remains paused. Deployment instructions: `docs/selectel-quickstart.md`; templates: `deploy/`; local build/archive: `bash scripts/package-selectel.sh <domain>`.
- LLM is disabled by default (`LLM_ENABLED=false`). The provider factory and request method both reject calls when disabled, even if keys exist. `ASSISTANT_ENABLED` also defaults to false and requires LLM_ENABLED. The app opens the calendar, hides the assistant, and provides a separate admin settings tab. Natural-language poll suggestions are disabled; explicit poll actions remain available.
- Public-comment moderation uses only `modules/moderation/rules.py`, with no LLM fallback. Existing scope, revision checks, admin exemptions and deletion audit remain. `MODERATION_AUTO_DELETE` retains its existing meaning and true default; false enables manual confirmation. Regex rules cannot interpret quotations and can miss unfamiliar spam.
- `RECOVERY_MODE=true` permits only root/health HTTP endpoints and local DB initialization/migrations; it starts no bot or background tasks. `POLL_AUTOMATION_ENABLED=false` suppresses automatic polls and reminders; normal polling, calendar/finance sync and voter registration/attendance export retries run outside recovery. Manual API actions are available outside recovery.
- Production runs one uvicorn worker from the server's own virtualenv, with SQLite outside the release at `/var/lib/foshoo/theater_bot.db`. No Yandex credentials or persistent Node server are needed. These templates do not yet configure automatic external backups.
- Assistant capability audit for this change: no new assistant tools are needed while disabled; old tools/context remain for a later explicit re-enable and review. Both assistant chat and action confirmation endpoints continue to reject requests when disabled.

### Assistant restored on Cloud.ru (21 October 2026)

- Production now runs on Cloud.ru (`docs/cloudru-migration.md`). The assistant is
  enabled with `LLM_PROVIDER=cloudru`, `CLOUDRU_MODEL=openai/gpt-oss-120b`,
  `LLM_MAX_TOKENS=4096`, `LLM_ENABLED=true` and `ASSISTANT_ENABLED=true`.
- `CLOUDRU_API_KEY` is backend-only, stored in `/etc/foshoo.env` on production.
  Cloud.ru uses Bearer auth, `max_completion_tokens`, and `parallel_tool_calls=false`.
  Yandex remains available through `LLM_PROVIDER=yandex`; absent provider defaults
  to Yandex for backward compatibility. No automatic provider fallback.
- Deployment templates still default LLM/assistant to off. Existing UI is reused;
  the initial tab stays calendar. Access restrictions and confirmation/replay
  protection remain intact. Moderation still uses local rules; automatic polls
  remain disabled on production.
- Live checks passed with synthetic context: tool-result roundtrip, expense
  lookup, and expense preview without executing the write. Server model response
  and signed app-config/hints endpoints were verified after restart.

### Release provenance (26 October 2026)

- Production is an archive installation without `.git`; push does not deploy it.
  Use the Cloud.ru commands in `docs/cloudru-migration.md`.
- Commit and push reviewed source before deployment. `scripts/package-selectel.sh`
  rejects tracked/untracked changes and builds from `git archive` of one commit;
  `REVISION` must describe the complete deployed code. Never bypass this guard
  or deploy working-tree files directly.
- `deploy/update-selectel.sh` uses the service's configured user (`foshoo-app`
  on Cloud.ru), backs up code/static/config/DB and rolls back code on failure.
  Verify revision, backend hashes, public index/JS and health after deployment.
- Local `output/`, `tmp/` and legacy `knowledge-base/` are ignored artifacts,
  excluded from releases. They are not sources of project context.

### AI comment moderation (27 October 2026)

- Replaces the historical local-rule moderation described above. `classifier.py`
  uses the assistant's `get_llm_client()` with a separate moderation prompt and no
  tools. Only comment text/caption and hidden links are model inputs; author data
  is retained for audit and admin exemptions. Strict results: spam/allow/review.
- Spam is auto-deleted when enabled; uncertainty, disabled/unavailable LLM and
  invalid responses require human validation. `MODERATION_AUTO_DELETE=false`
  also requires validation for confident spam. No regex fallback.
- SQLite decisions last 24 hours without sliding expiry. Cosmetic text variants
  share a key across authors; words, punctuation and hidden link targets remain
  significant. Model allow decisions are not cached; human decisions are.
- Repeated review comments share one durable validation card. Confirmation checks
  each stored revision and current admin status before deletion. Edits invalidate
  their old membership; duplicate callbacks and uncertain deletions never retry
  destructive actions. Existing legacy callback cards remain supported.
- New tables are created by startup `create_all`; existing comment audit is kept.
  Deployed to Cloud.ru as `49b0f6253ec071f610e3bdc6d2fb4daf5e9cf943`.
  Model, Telegram permissions, DB integrity, polling, health and release hashes
  verified after deployment; see `docs/cloudru-migration.md` for the backup.
