# Infrastructure (as implemented)

## 1. Compose stack — `docker-compose.yml` (lean default)

| Service | Image | Notes |
|---|---|---|
| **db** | `postgres:16-alpine` | `POSTGRES_USER/PASSWORD/DB` from env; volume `pgdata`; healthcheck `pg_isready`; host port **55432**→5432 (used by the backend test-suite too) |
| **redis** | `redis:7-alpine` | AOF persistence; volume `redisdata`; healthcheck `redis-cli ping`; host port **56379**→6379 |
| **api** | built from `./backend/Dockerfile` (or `${IMAGE_REGISTRY}/api:${IMAGE_TAG}`) | Runs `alembic upgrade head && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000`; host port `${API_HOST_PORT:-8100}`→8000; volume `mediadata:/srv/data/media` (`LOCAL_STORAGE_DIR`); depends on db+redis healthy |
| **frontend** | built from `./frontend/Dockerfile` | Nuxt SSR/generate app served behind bundled web server; host port `${FRONTEND_PORT:-80}` |
| rabbitmq | `rabbitmq:4-management-alpine` | **profile `queue` only** (off by default) |
| telegram-bot | `./backend/Dockerfile.telegram` | **profile `telegram` only** (optional view-only inquiry bot) |

Scheduling: none. The daily expiry-alert scan runs **inside the API process** (`core/scheduler.py`, asyncio task + Redis NX lock). Celery worker/beat containers do not exist in the default stack (`tasks/celery_app.py` remains dormant code; the `queue` profile exists for future optional use).

`docker-compose.prod.yml` overlay: sets `ENVIRONMENT=production`, pulls prebuilt GHCR images (`pull_policy`), disables private-network CORS, and is validated in CI with production-like env values.

## 2. Storage

- **Local disk only** (no S3/MinIO):
  - `LOCAL_STORAGE_DIR` (default `var/media`; container `/srv/data/media`) — product/brand/shop images uploaded via `POST /images/upload` (5 MB cap, image content types, traversal-safe serving via `GET /images/{key}`). No invoice files are stored anywhere — invoices print from HTML in the browser.
- **Redis** — transient state only: rate-limit counters, hashed reset codes, refresh-JTI revocation, settings/dashboard cache, scheduler lock. Nothing durable lives here; PostgreSQL is authoritative.

## 3. Backend runtime

- Uvicorn ASGI, async SQLAlchemy engine pool (`db_pool_size=10`, `max_overflow=20`), `DB_ECHO` off.
- Lifespan: `assert_safe_for_production()` → optional scheduler start → (shutdown) scheduler stop + Redis close.
- Logging: structured `stock_pos` logger via `core/logging.py`; `X-Request-ID` correlation header on every response.
- Alembic runs **on container start** (deploy-time migration), followed by the idempotent seed (permission catalog sync, Administrator + seed admin, default sequences, default UOMs, walk-in customer; dev-only sample data).

## 4. Frontend runtime

- Nuxt 4 (`nuxt generate` output), API base from `NUXT_PUBLIC_API_BASE` runtime config (same-origin `/api` in the nginx-served compose setup).
- CI builds with `pnpm install --frozen-lockfile`, `prepare:nuxt`, `test` (Vitest), `typecheck`.

## 5. Telegram

- Bot token arrives only via env/DB secret (`TELEGRAM_BOT_TOKEN` / `telegram.bot_token` setting, masked in the API); never exposed to the SPA.
- The API process sends password-reset codes, payment notification texts and expiry alerts through `shared/telegram/client.py` (HTTP). The optional `telegram-bot` profile runs `telegram_bot.py` for view-only stock inquiry with a service-token handshake (`TELEGRAM_BOT_CLIENT_ID/SECRET`, 10-minute service tokens).

## 6. CI/CD — `.github/workflows/`

- **ci.yml** (PR + main):
  1. `compose`: `docker compose -f docker-compose.yml config --quiet` (+ prod overlay with CI secrets).
  2. `frontend`: pnpm install → prepare → `pnpm test` → `pnpm typecheck`.
  3. `backend`: pytest against service containers (postgres 55432, redis 56379).
- **publish-images.yml** (main + `v*` tags): buildx builds and pushes `api`, `frontend`, `telegram-bot` images to `ghcr.io/<owner>/stock_pos/*`.

## 7. Configuration sources

`.env` (dev, see `.env.example`) and `.env.production.example` feed compose variables (`POSTGRES_*`, `JWT_SECRET_KEY`, `TELEGRAM_*`, `SEED_ADMIN_*`, `CORS_ORIGINS`, `CORS_ALLOW_PRIVATE_NETWORKS`, `API_HOST_PORT`, `FRONTEND_PORT`, `LOCAL_STORAGE_DIR`, `IMAGE_REGISTRY`, `IMAGE_TAG`). The backend validates the production profile at boot and refuses unsafe combos (placeholder secrets, DEBUG=true, private-network CORS) — see [BACKEND.md](BACKEND.md) §2.

## 8. Source-tree notes

- `infrastructure/` contains nginx config and helper scripts used by image builds.
- `var/` (media) and `backend/var/` are local runtime directories, git-ignored content-wise but present for dev runs.
- `vercel.json` exists for an optional static frontend deployment target; the supported path is the compose stack.
