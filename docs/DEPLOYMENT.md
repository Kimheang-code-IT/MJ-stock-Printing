# Deployment (as implemented)

## 1. Supported deployment: Docker Compose

### Development / first run
```bash
cp .env.example .env            # adjust ports/secrets as needed
docker compose up -d --build    # db + redis + api + frontend
```
- API on `http://localhost:${API_HOST_PORT:-8100}` (docs at `/docs` — dev only), frontend on `http://localhost:${FRONTEND_PORT:-80}`.
- On start the api container runs `alembic upgrade head`, then `python -m app.seed` (permission catalog, Administrator role + seed admin from `SEED_ADMIN_*`, default document sequences, default UOMs, walk-in customer), then uvicorn.
- Login with `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` and complete setup via **Administration → Settings**, or use `/auth/setup` on an empty database.

### Production (another host, prebuilt images)
```bash
cp .env.production.example .env # strong JWT secret, Telegram token, CORS origins, SEED_ADMIN_*
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
Images come from `ghcr.io/kimheang-code-it/stock_pos/{api,frontend,telegram-bot}` (override with `IMAGE_REGISTRY`/`IMAGE_TAG`). Production boot fails fast unless: `JWT_SECRET_KEY` ≥ 32 chars and non-placeholder, `TELEGRAM_BOT_CLIENT_SECRET` non-placeholder, `SEED_ADMIN_PASSWORD` ≥ 12 chars non-placeholder, `DEBUG=false`, `CORS_ALLOW_PRIVATE_NETWORKS=false`, `ENVIRONMENT=production`. API docs/openapi are disabled in production.

### Profiles
```bash
docker compose --profile telegram up -d   # optional view-only inquiry bot
docker compose --profile queue up -d      # RabbitMQ (only if Celery features are ever enabled)
```
Neither is required: expiry alerts run in-process, Telegram sending is HTTP from the API.

## 2. Environment variables

| Variable | Used by | Default (dev) |
|---|---|---|
| `POSTGRES_USER/PASSWORD/DB` | db + api | stock_pos / stock_pos / stock_pos |
| `DATABASE_URL` | api (inside compose it is assembled from POSTGRES_*) | `postgresql+asyncpg://…@db:5432/stock_pos` |
| `REDIS_URL` | api | `redis://redis:6379/0` |
| `JWT_SECRET_KEY` | api | dev placeholder (**must** change) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | api | 15 / 7 |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_CLIENT_ID/SECRET`, `TELEGRAM_BOT_MODE` | api, telegram-bot profile | empty / stock-pos-telegram(-bot) / polling |
| `FRONTEND_BASE_URL` | api (Telegram deep links) | empty |
| `EXPIRY_ALERT_SCAN_HOUR` (UTC), `SCHEDULER_ENABLED` | api | 7 / true |
| `SEED_ADMIN_EMAIL/PASSWORD/NAME` | api seed | admin@gmail.com / 123456 / System Administrator |
| `CORS_ORIGINS`, `CORS_ALLOW_PRIVATE_NETWORKS` | api | localhost list / true (dev) |
| `API_HOST_PORT`, `FRONTEND_PORT` | compose host ports | 8100 / 80 |
| `LOCAL_STORAGE_DIR`, `MAX_UPLOAD_BYTES` | api | var/media, 5 MB |
| `RATE_LIMIT_*` | api | login 10/min, refresh 30/min, reset 5/hour |
| `IMAGE_REGISTRY`, `IMAGE_TAG` | compose image refs | ghcr path / local |

## 3. Data & volumes

- `pgdata` — all authoritative data (products, stock, sales, debts, sequences, settings, audit).
- `redisdata` — transient only; safe to lose.
- `mediadata:/srv/data/media` — uploaded images (`LOCAL_STORAGE_DIR`). No invoice/report files are stored server-side, so the database plus the media volume are the only things to back up.

## 4. Upgrades & rollback

1. Pull/build new images; `docker compose up -d` re-runs `alembic upgrade head` on api start (migrations are append-only, `backend/alembic/versions/0001…0017`).
2. Seed is idempotent — safe on every boot.
3. Rollback = redeploy previous image tag; if a migration must be reverted use `alembic downgrade` deliberately (never edit production tables by hand).

## 5. Health & operations

- `GET /health` (and `/api/v1/health`) — liveness incl. DB/Redis status; compose healthchecks cover db/redis.
- Logs: container stdout (structured `stock_pos` logger, `X-Request-ID` per request).
- Daily expiry scan result lines appear in api logs (`Expiry alert sweep: {…}`).
- Backups: `pg_dump` the db volume; back up the media volume.

## 6. Non-container / manual run (development)

```bash
# backend
cd backend && python -m venv .venv && . .venv/Scripts/activate  # (Windows Git Bash)
pip install -r requirements.txt
alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload --port 8100

# frontend
cd frontend && pnpm install && pnpm dev        # expects API at NUXT_PUBLIC_API_BASE
```

## 7. Pre-flight checklist (production)

- [ ] All placeholder secrets replaced; `docker compose … config` validated in CI.
- [ ] `ENVIRONMENT=production`, `DEBUG=false`, private-network CORS off, real `CORS_ORIGINS`.
- [ ] Strong `SEED_ADMIN_*`; change the admin password after first login.
- [ ] Telegram bot token configured (Settings → Telegram or env) and admin chat ids linked.
- [ ] Volumes present (pgdata, redisdata, mediadata) and backup schedule defined.
- [ ] `docker compose config --quiet` passes for the prod overlay.
