# PVZ Purple Zone Monitor - Telegram-First MVP (Phase 2)

Project now includes:
- background monitoring core (scheduler + CV + diff + change events)
- Telegram bot as primary user UX
- REST API for upcoming web cabinet

## Architecture

```text
app/
  main.py                 # worker entrypoint (scheduler + bot)
  api/main.py             # FastAPI app entrypoint
  core/                   # settings, logging, exceptions
  db/                     # SQLAlchemy models, repositories, schema init/migration
  services/               # monitoring, CV, matching, subscriptions, mvp service
  scheduler/              # periodic checks
  bot/                    # Telegram UX
tests/
```

## Data Model

Core entities:
- `users`
- `tracked_items`
- `zone_snapshots`
- `detected_zones`
- `change_events`

Supports multiple tracked items per user.

## Tariff Logic (MVP)

Plans and limits:
- `trial` / `free`: up to `1` tracked item
- `base`: up to `5` tracked items
- `pro`: up to `20` tracked items

Enforced on tracked-item creation.
Tariff expiration blocks new tracked-item creation and manual checks.

## Telegram Bot UX

Main entry:
- `/start`

Menu actions:
- `Add Tracking`
- `My Trackings`
- `Event History`
- `Check History`
- `Tariff`
- `Help`

Implemented flows:
- add new tracking (link -> optional title -> first check -> activation)
- list tracked items with actions:
  - check now
  - enable/disable
  - delete
  - details
- view latest events and latest checks
- view tariff status
- receive change notifications from scheduler (text + diff image when available)

## API (for Web Cabinet)

Base endpoints:
- `GET /api/me`
- `GET /api/tracked-items`
- `POST /api/tracked-items`
- `GET /api/tracked-items/{id}`
- `POST /api/tracked-items/{id}/check`
- `PATCH /api/tracked-items/{id}`
- `DELETE /api/tracked-items/{id}`
- `GET /api/tracked-items/{id}/snapshots`
- `GET /api/tracked-items/{id}/events`

Extra:
- `GET /health`

### Dev Auth

Current phase uses dev-auth headers:
- `X-Dev-Telegram-Id` (required)
- `X-Dev-Username` (optional)
- `X-Dev-Full-Name` (optional)

Example:

```bash
curl -H "X-Dev-Telegram-Id: 12345" http://localhost:8000/api/me
```

## Configuration

1. Create `.env` from template:

```bash
cp .env.example .env
```

2. Key variables:
- `TELEGRAM_BOT_TOKEN`
- `ENABLE_BOT`
- `ENABLE_SCHEDULER`
- `DATABASE_URL`
- `MAX_ITEMS_TRIAL_FREE`, `MAX_ITEMS_BASE`, `MAX_ITEMS_PRO`
- browser settings (`CHROME_BINARY_PATH`, `CHROMEDRIVER_PATH`)

## Run Locally

Install:

```bash
pip install -r requirements.txt
```

Run worker (scheduler + bot):

```bash
python -m app.main
```

Run single scheduler iteration:

```bash
RUN_ONCE=true python -m app.main
```

Run API:

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker compose up --build
```

Services:
- `worker` (scheduler + bot)
- `api` (FastAPI)

## Logging

Logs include:
- user actions in bot
- tracked-item create/update/delete
- manual checks
- notification attempts
- scheduler and scraping errors

## Tests

Run:

```bash
pytest
```

Covered baseline:
- contour-based detection
- zone matching
- snapshot + change event generation
- tariff limits
- API tracked-item flow

## Notes

- Legacy prototype file `pvz_map.py` is kept for reference.
- Payment is still mocked (tariff switching is test-mode), but architecture is prepared for real payment integration.
