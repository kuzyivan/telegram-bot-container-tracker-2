# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the bot locally
python bot.py

# Run the web app (FastAPI, port 8002)
cd web && uvicorn main:app --host 0.0.0.0 --port 8002

# Apply DB migrations
alembic upgrade head

# Generate a new migration from model changes
alembic revision --autogenerate -m "description"

# Lint
ruff check .

# Run tests
pytest tests/

# Deploy to VPS (SSH trigger)
make deploy
```

Service management on the VPS:
```bash
systemctl restart atermtrackbot.service   # Telegram bot (webhook, port 8050)
systemctl restart kuzyadmin.service       # FastAPI web app (port 8002)
```

## Architecture

The project is two independent processes sharing one PostgreSQL database:

1. **Telegram Bot** (`bot.py`) — webhook mode via nginx → `127.0.0.1:8050`. Runs APScheduler internally for all background jobs.
2. **FastAPI Web App** (`web/main.py`) — admin panel + client cabinet on port 8002. Served at `/` by nginx.

Deployment: push to `main` triggers GitHub Actions → `rsync` to VPS → `systemctl restart atermtrackbot.service`.

### Layers

- `handlers/` — PTB handlers. Multi-step flows use `ConversationHandler`. All admin commands live in `handlers/admin/`.
- `queries/` — all SQLAlchemy queries, one file per domain. **Never put DB queries directly in handlers.**
- `services/` — business logic: IMAP polling, Excel parsing, notification batching, distance calculation, train event notifier.
- `models.py`, `model/terminal_container.py`, `models_finance.py` — ORM models split across three files.
- `utils/` — helpers: `notify.py` (`notify_admin()`), `send_tracking.py` (Excel export), `email_sender.py`.
- `scheduler.py` — all APScheduler jobs. Timezone is **Asia/Vladivostok (UTC+10)**.

### Databases

`db.py` sets up two async SQLAlchemy engines:
- `SessionLocal` — main DB (`DATABASE_URL`) for users, subscriptions, tracking, trains, finances.
- `TariffSessionLocal` — read-only tariff DB (`TARIFF_DATABASE_URL`).

**Critical:** every ORM model file must be explicitly imported in `db.py` (even if unused elsewhere) so that Alembic and SQLAlchemy relationship resolution can see them. Currently: `models.py`, `model/terminal_container.py`, `models_finance.py`.

### Scheduler jobs

All jobs run in Asia/Vladivostok time:
- `09:00` and `16:00` — `job_send_notifications` (subscription reports via Telegram + email)
- Every `20 min` — `job_periodic_dislocation_check` (polls IMAP for new dislocation Excel files)
- `08:30` and `11:30` — `job_daily_terminal_import` (IMAP → terminal container DB)
- `17:10` daily — `job_cleanup_old_stocks` (clear stock_info for trains older than 3 days)
- On startup — `job_dislocation_check_on_start` runs as `asyncio.create_task()` (non-blocking)

### Webhook / nginx

- Bot listens on `127.0.0.1:8050`, path `/tgbot/17f491a19ee000d8b124/`
- nginx proxies `logistrail.ru/tgbot/` → bot, `logistrail.ru/` → web app
- Webhook config lives in `config.py`: `WEBHOOK_HOST`, `WEBHOOK_PATH`, `WEBHOOK_PORT`

### `zdtarif_bot/`

Embedded as a library for `/distance` tariff distance calculations. Not a separate running process.
