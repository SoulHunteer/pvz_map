# PVZ Purple Zone Monitor - Telegram + Web MVP

Полный MVP включает:
- backend API + scheduler + CV-ядро (contour/polygon detection)
- Telegram-бот для уведомлений и ручных действий
- web cabinet для управления отслеживаниями

## Архитектура

```text
app/
  main.py                 # worker: scheduler + bot
  api/main.py             # FastAPI entrypoint
  api/router.py           # REST endpoints
  core/                   # settings, logging, exceptions
  db/                     # SQLAlchemy models, repositories, schema init
  services/               # monitoring, scraper, image_detection, matching, mvp logic
  scheduler/              # background checks
  bot/                    # Telegram bot runner + handlers
frontend/
  src/                    # React + TS web cabinet
  Dockerfile              # frontend image
  nginx.conf              # reverse proxy to backend API
tests/
```

## Ключевые возможности MVP

- Multiple tracked items на одного пользователя
- Snapshot history + change events
- Improved matching зон между проверками
- Telegram уведомления при изменениях
- Ручные проверки и фоновые проверки
- Web cabinet:
  - Dashboard
  - Мои отслеживания
  - Создание отслеживания
  - Детали отслеживания (snapshots/events/images)
  - Тариф и лимиты

## Data model

Сущности:
- `users`
- `tracked_items`
- `zone_snapshots`
- `detected_zones`
- `change_events`

## API

Доступные endpoints:
- `GET /health`
- `GET /api/me`
- `GET /api/tracked-items`
- `POST /api/tracked-items`
- `GET /api/tracked-items/{id}`
- `POST /api/tracked-items/{id}/check`
- `PATCH /api/tracked-items/{id}`
- `DELETE /api/tracked-items/{id}`
- `GET /api/tracked-items/{id}/snapshots`
- `GET /api/tracked-items/{id}/snapshots/{snapshot_id}/zone-diff`
- `GET /api/tracked-items/{id}/events`

Отдача файлов артефактов:
- `GET /artifacts/screenshots/<file>`
- `GET /artifacts/processed/<file>`
- `GET /artifacts/diffs/<file>`

## Dev auth (MVP)

Для API и web cabinet используется dev-auth заголовками:
- `X-Dev-Telegram-Id` (обязательный)
- `X-Dev-Username` (опционально)
- `X-Dev-Full-Name` (опционально)

Web cabinet хранит эти значения локально и подставляет в каждый запрос.

## Тарифы и лимиты

- `trial/free`: до `1` tracked item
- `base`: до `5`
- `pro`: до `20`

Лимиты проверяются в business-логике на создании новых отслеживаний.
При истечении тарифа блокируются создание и ручные проверки.

## Конфигурация

1. Создать `.env`:

```bash
cp .env.example .env
```

2. Важные переменные backend:
- `TELEGRAM_BOT_TOKEN`
- `ENABLE_BOT`, `ENABLE_SCHEDULER`
- `DATABASE_URL`
- `API_CORS_ORIGINS`
- `ALLOWED_TELEGRAM_USER_IDS`, `ADMIN_TELEGRAM_USER_IDS`
- `MAX_ITEMS_TRIAL_FREE`, `MAX_ITEMS_BASE`, `MAX_ITEMS_PRO`

3. Важные переменные frontend (`frontend/.env`):
- `VITE_API_BASE_URL` (например `http://localhost:8000`)
- `VITE_ASSET_BASE_URL` (обычно тот же backend)

## Локальный запуск

### Backend зависимости

```bash
pip install -r requirements.txt
```

### Запуск API

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

### Запуск bot (scheduler + bot)

```bash
python -m app.main
```

### Запуск web cabinet

```bash
cd frontend
npm install
npm run dev
```

Frontend по умолчанию: `http://localhost:5173`.

## Docker запуск (полный MVP)

```bash
docker compose up --build
```

Сервисы:
- `bot` (scheduler + bot)
- `api` (FastAPI)
- `frontend` (Nginx + React build) на `http://localhost:3000`

## Тесты

```bash
pytest
```

Покрытие базового ядра:
- detection
- zone matching
- monitoring pipeline
- subscription limits
- API tracked-item flow

## Ограничения MVP

- Нет production auth и оплаты (dev-auth + mock тарификация)
- Frontend рассчитан на MVP-функции без расширенной аналитики
- CV детектирование зависит от визуального стиля карты WB и требует периодической калибровки порогов



