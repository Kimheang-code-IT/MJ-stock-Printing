# Local-only Windows deployment (C:\StockPOS)

Single-PC, production-style deployment of the Stock & POS system. The client
turns the computer on and the browser opens the app — no commands required.

Architecture (never anything else — no RabbitMQ, no Celery worker, no scheduler
container, no MinIO/S3, no backend PDF service, no desktop/Electron runtime):

```text
Windows PC
  └─ Docker Desktop (starts at sign-in)
       ├─ frontend   nginx + Nuxt SPA  → published on 127.0.0.1:80 (http://localhost)
       ├─ api        FastAPI            → internal network only; runs the
       │                                 in-process scheduler (expiry alerts,
       │                                 Telegram sends, daily summary)
       ├─ db         PostgreSQL 16      → internal network only (authoritative)
       └─ redis      Redis 7            → internal network only (transient)
```

The browser talks to **http://localhost only**. The frontend nginx container
proxies `/api/` and `/health/` to the API container, so the API port is never
published. PostgreSQL and Redis are never reachable from the host or LAN.

## 1. First installation (done once, by the installer/technician)

1. Install **Docker Desktop for Windows** and restart the PC.
2. Create the deployment folder `C:\StockPOS\` and copy into it:
   - `docker-compose.yml` and `docker-compose.local.yml` (compose stack)
   - the `backend\` and `frontend\` image sources (first build) **or** exported
     image archives (see §9)
   - `infrastructure\scripts\stockpos\` (all `.bat`/`.ps1` files)
   - `.env` — copy from `.env.local.example` and replace every `CHANGE_ME`
     with a strong unique secret. At minimum:
     - `JWT_SECRET_KEY` (32+ chars, e.g.
       `python -c "import secrets; print(secrets.token_urlsafe(48))"`)
     - `POSTGRES_PASSWORD`
     - `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` (12+ chars)
     - `TELEGRAM_BOT_CLIENT_SECRET` (any strong value; the bot token itself is
       optional — leave `TELEGRAM_BOT_TOKEN=` empty to disable Telegram)
3. Start once and let images build (only the first time):
   `C:\StockPOS\infrastructure\scripts\stockpos\start-system.bat`
4. Open `http://localhost` (via `open-system.bat`), sign in with the seed
   admin, then **change the password immediately** and complete
   Administration → Settings.

The API boots in this order on every start (safe, idempotent):

```text
alembic upgrade head   (append-only migrations — never resets data)
python -m app.seed     (permission catalog, roles, default sequences/UOMs,
                        walk-in customer; skips whatever already exists)
uvicorn (the API serves; in-process scheduler starts)
```

An existing client database is **never** reset or recreated automatically.

## 2. Docker Desktop configuration

Open **Docker Desktop → Settings → General** and enable:

- ✅ *Start Docker Desktop when you sign in*

That is the supported auto-start mechanism. Do not use registry hacks. The
compose services themselves use `restart: unless-stopped`, so as soon as the
Docker engine is running they come back up on their own.

## 3. First startup

1. Turn the PC on (Docker Desktop starts at sign-in).
2. Containers restart automatically (or double-click `start-system.bat`).
3. Double-click `wait-and-open-system.bat` — it waits for Docker, waits for
   the health endpoint, then opens the browser.
4. Sign in and use the system.

## 4. Automatic startup (installed by `install-autostart.bat`)

`install-autostart.bat` adds a **current-user** Startup shortcut (no
administrator rights needed):

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Stock and POS (wait and open).lnk
```

At every sign-in it runs `wait-and-open-system.bat`, which:

1. polls `docker info` until the engine is ready (default 10 min),
2. starts the compose stack if it is not already running (no rebuild),
3. polls `GET http://localhost/health/ready` every 3 s (default 10 min) — the
   endpoint reports `ok` only when PostgreSQL **and** Redis respond,
4. opens `http://localhost` in the default browser — exactly once
   (a named-mutex guard prevents duplicate windows from racing runs).

Logs land in `%TEMP%\stockpos-autostart.log`. Remove it any time with
`remove-autostart.bat`.

### How to disable auto-open

- Run `remove-autostart.bat` (or delete the Startup shortcut) — the containers
  still start with Docker Desktop, but no browser window opens at sign-in.
  Double-click the "Yoeun Sokhon Pharmacy" desktop shortcut whenever needed.

## 5. Desktop shortcut

`install-desktop-shortcut.bat` creates **"Yoeun Sokhon Pharmacy"** on the
current user's desktop. It calls `open-system.bat`, which opens
`http://localhost` (and waits up to 90 s for health if the app is still
starting). If `stockpos.ico` exists next to the scripts it is reused for the
icon; otherwise a built-in Windows icon is used — no binary assets are
invented.

Normal client workflow:

```text
Turn on PC → wait → browser opens → login → use system
If the browser closes: double-click "Yoeun Sokhon Pharmacy"
```

## 6. Manual start / stop / restart

| Script | Action |
|---|---|
| `start-system.bat` | `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d` (detached; no rebuild unless images are missing) |
| `stop-system.bat` | `docker compose … stop` — **never** `down -v`; all volumes preserved |
| `restart-system.bat` | `docker compose … up -d` — re-creates only changed containers; migrations run on API start; data preserved |
| `open-system.bat` | opens `http://localhost` in the default browser |
| `wait-and-open-system.bat` | waits for Docker + health, then opens once |
| `install-autostart.bat` / `remove-autostart.bat` | manage the Startup entry |
| `install-desktop-shortcut.bat` | create the desktop shortcut |

All scripts use `C:\StockPOS` by default (override with the `STOCKPOS_DIR`
environment variable). Every script shows a plain-language error when Docker
is not available and points to `wait-and-open-system.bat`.

## 7. Health checks (compose-defined, not sleeps)

| Service | Check |
|---|---|
| `db` | `pg_isready` (compose healthcheck) |
| `redis` | `redis-cli ping` |
| `api` | `GET /health/ready` — ok only when PostgreSQL + Redis answer |
| `frontend` | container nginx serves `GET /` (in-image healthcheck) |

Startup order: `db`/`redis` healthy → `api` (runs migrations, then serves;
compose waits for the API deep-health) → `frontend`. No arbitrary sleeps.

Browser-facing health: `http://localhost/health/ready` (same-origin via the
frontend nginx `/health/` proxy) and `http://localhost/health`.

## 8. Backup

Two things are authoritative and must be backed up. Everything else
(Redis, containers) is disposable.

| What | Where | How |
|---|---|---|
| PostgreSQL | `pgdata` volume (stock, sales, debts, sequences, settings, audit) | `docker exec stockpos-db-1 pg_dump -U stock_pos stock_pos > backup.sql` (run regularly; keep copies **outside the PC** as well) |
| Uploaded images / shop logo | `mediadata` volume (`/srv/data/media` inside the api container) | `docker run --rm -v stockpos_mediadata:/data -v C:\StockPOS\backups:/backup alpine tar czf /backup/media-YYYYMMDD.tar.gz -C /data .` |

- Redis (`redisdata`) is transient — no authoritative backup needed.
- Invoices are **not** stored server-side (browser printing only), so nothing
  else needs backing up.
- Keep backups in `C:\StockPOS\backups\` and copy them to an external drive.

## 9. Restore

1. Stop the system (`stop-system.bat`).
2. PostgreSQL: `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d db`
   then
   `docker exec -i stockpos-db-1 psql -U stock_pos -d stock_pos < backup.sql`
3. Media: `docker run --rm -v stockpos_mediadata:/data -v C:\StockPOS\backups:/backup alpine sh -c "rm -rf /data/* && tar xzf /backup/media-YYYYMMDD.tar.gz -C /data"`
4. `start-system.bat`, then verify `http://localhost/health/ready` shows
   `"status":"ok"`.

## 10. Upgrade

1. (Optional but recommended) Back up first — see §8.
2. Stop the app: `stop-system.bat` (volumes untouched).
3. Update the application: either `git pull` in the deployment folder and run
   `start-system.bat` **once with the install flag** (rebuild from source:
   `docker compose -f docker-compose.yml -f docker-compose.local.yml build`),
   or load new exported images:
   `docker load -i stockpos-api-vN.tar.gz` / `...frontend-vN.tar.gz`.
4. `start-system.bat` — containers are re-created with the new image, the API
   runs `alembic upgrade head` (append-only), the seed is idempotent, volumes
   are preserved.
5. Verify: `docker compose ps` (all four healthy) and
   `http://localhost/health/ready`.

Rollback = redeploy the previous image tag (or previous git checkout +
rebuild). `docker compose down -v` is **never** used during normal upgrades.

## 11. Security posture (local-only)

- Frontend binds to `127.0.0.1:80` (`FRONTEND_BIND=127.0.0.1` in `.env`) —
  reachable from this PC only.
- PostgreSQL and Redis are **not published at all** (internal Docker network
  only). They are never reachable from the host or LAN.
- API port is not published; browser calls are same-origin through the
  frontend nginx (`/api/`, `/health/`).
- To allow LAN access later (explicit decision, not a default): set
  `FRONTEND_BIND=<LAN IP or 0.0.0.0>` in `.env` and add the LAN origin to
  `CORS_ORIGINS`, e.g. `http://192.168.1.50`, then run `restart-system.bat`.
  PostgreSQL/Redis remain unpublished.
- `ENVIRONMENT=production`, `DEBUG=false` — the API refuses to boot with
  development secrets (JWT secret ≥ 32 chars, non-placeholder seed admin
  password, `CORS_ALLOW_PRIVATE_NETWORKS=false`).
- No dev bind mounts, no hot reload in the local-prod stack.

## 12. Troubleshooting

| Symptom | What to do |
|---|---|
| "Docker is not available yet" | Start Docker Desktop from the Start menu; confirm "Start Docker Desktop when you sign in" is enabled; retry or use `wait-and-open-system.bat`. |
| Browser shows connection refused | The stack is still starting — wait ~1 minute (first start after a PC reboot takes a few minutes) or run `restart-system.bat`. |
| Port 80 already allocated (only relevant when another app owns port 80) | Set `FRONTEND_PORT=8080` (or any free port) in `.env` and run `restart-system.bat`; then use `http://localhost:8080`. |
| Need to see what is happening | `docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f api` (run inside `C:\StockPOS`). |
| Auto-open stopped working | Re-run `install-autostart.bat`; check `%TEMP%\stockpos-autostart.log`. |
| Forgot the admin password | Use the Telegram password reset (if Telegram is configured) or restore the database from backup. |
| Disk full from old images | `docker image prune -f` — never `docker volume prune` on the client PC. |

## 13. What runs where (summary)

| Scheduled job | Runs inside | Container |
|---|---|---|
| Daily expiry alerts | `app/core/scheduler.py` | `api` (in-process) |
| Telegram sale / purchase / debt-payment texts | after commit in the API | `api` |
| Daily Telegram summary | after the expiry slot | `api` |

No scheduler container, no queue, no object store — by design.