# Infrastructure — Stock & POS

Everything needed to run Stock & POS in Docker lives in **this folder**:
the Compose files, the `.env` templates, the Windows launchers, and the helper
scripts. The application code stays in `../backend` and `../frontend`; the
Compose files build from those folders.

- `docker-compose.yml` — the **single** stack (`mj-stock-management-db`, `mj-stock-management-redis`, `mj-stock-management-api`, `mj-stock-management-frontend`, `mj-stock-management-telegram-bot`).
- `.env.local.example` — template for the local-only run (recommended).
- `Start MJ.bat` / `Stop MJ.bat` — one-click daily use.
- `First Time Setup.bat` — first run (creates `.env`, builds, starts).
- `scripts/` — PowerShell helpers (see the bottom of this file).
- `nginx/` — host reverse-proxy configs; `nginx/mj.conf` is a ready-to-use HTTPS (TLS) front for production.

## 1. Local-only deployment in one minute (Windows PC)

Requirements: **Docker Desktop** installed and running. Git is optional (only
needed for the clone/upgrade step).

1. Get the code (pick one):
   - `git clone https://github.com/Kimheang-code-IT/stock_pos.git`
   - or download the ZIP and unzip it.
2. Open this `infrastructure` folder.
3. Double-click **`First Time Setup.bat`** and wait. It:
   - generates `infrastructure\.env` with strong random secrets,
   - builds the API + frontend images from source (no GHCR account needed),
   - starts PostgreSQL, Redis, API and frontend,
   - prints the administrator email and password — **save them**.
4. Double-click **`Start MJ.bat`** (or open <http://localhost>).

In the local-only mode the app binds to **`127.0.0.1:80`**, so it is reachable
from this computer only. PostgreSQL, Redis and the API are **not** published to
the host at all — they stay on the internal Docker network.

## 2. Daily use

| Action | How |
|---|---|
| Start and open the app | double-click `Start MJ.bat` |
| Stop safely | double-click `Stop MJ.bat` |
| Restart | `scripts\mj\restart-system.bat` |
| Start automatically at sign-in | `scripts\mj\install-autostart.bat` |
| Desktop shortcut | `scripts\mj\install-desktop-shortcut.bat` |
| Remove auto-start | `scripts\mj\remove-autostart.bat` |

`Start MJ.bat` waits for Docker Desktop and for `GET /health/ready`
(which checks PostgreSQL and Redis) before opening the browser, so it is safe
to double-click right after logging in.

## 3. Configuration (`infrastructure\.env`)

`init-env.ps1` fills the secrets for you. The settings you may change:

| Key | Meaning |
|---|---|
| `FRONTEND_PORT` | host port for the app (default `80`). |
| `FRONTEND_BIND` | `127.0.0.1` = this PC only (default); set a LAN IP or `0.0.0.0` for LAN access. |
| `TELEGRAM_BOT_TOKEN` | optional; leave empty to disable Telegram. |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` | unused at startup; kept only for an explicit `python -m app.seed` run. |
| `COMPOSE_PROJECT_NAME` | defaults to `mj-stock-management`; set to `stockmanagement` only to reuse very old volumes. |

> Never commit `.env` — it contains secrets. It is already git-ignored.

### LAN access (optional)
Set `FRONTEND_BIND=0.0.0.0` (or the PC's LAN IP) in `.env`, then
`scripts\mj\restart-system.bat`. Add your frontend URL to `CORS_ORIGINS`
if you keep `ENVIRONMENT=production`.

## 4. Data, backups and reset

PostgreSQL data, Redis data and uploaded images live in Docker **named
volumes** (`mj-stock-management-pgdata`, `mj-stock-management-redisdata`, `mj-stock-management-mediadata`) —
they survive `Stop MJ.bat` and image rebuilds.

Back up the database:
```powershell
docker compose exec -T mj-stock-management-db pg_dump -U mj mj > backup.sql
```
Restore:
```powershell
Get-Content backup.sql | docker compose exec -T mj-stock-management-db psql -U mj mj
```
Uploaded images are in the `mj-stock-management-mediadata` volume. To erase everything and
start over (destructive):
```powershell
docker compose -f docker-compose.yml down -v
```

## 5. Upgrade

```powershell
git pull
.\scripts\install-client.ps1 -SkipGitPull   # rebuild images and restart
```
The API entrypoint runs `alembic upgrade head` on every start, so schema changes
apply automatically and existing data is preserved.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Browser shows a connection error | `Start MJ.bat`, wait ~1 minute, retry. |
| "Docker is not available yet" | Start **Docker Desktop** and enable *Start Docker Desktop when you sign in*. |
| Port 80 already in use | set `FRONTEND_PORT=8080` in `.env`, then restart. |
| Login fails after setup | the first administrator is created on the app's **Setup** page; no credentials are seeded. |
| Need logs | `docker compose logs -f mj-stock-management-frontend mj-stock-management-api` (run from this folder). |
| Wrong timezone/alerts | check `SCHEDULER_ENABLED` / `DAILY_SUMMARY_SCAN_HOUR` in the API settings. |

## 7. Scripts reference

| Script | Purpose |
|---|---|
| `scripts\init-env.ps1` | Create `.env` with strong random secrets. |
| `scripts\install-client.ps1` / `.sh` | Clone + build + start from source. |
| `scripts\deploy-from-registry.ps1` / `.sh` | Pull prebuilt GHCR images and start (remote prod). |
| `scripts\start-docker.ps1` / `.sh` | Start the **development** stack (`docker compose up -d --build`). |
| `scripts\prepare-production.ps1` | First-time local prep (creates `.env`, cleans caches). |
| `scripts\mj\*` | Daily-use helpers behind the `.bat` files. |

Advanced Compose usage (run from this folder, where `.env` lives):
```powershell
docker compose up -d --build        # build images and start
docker compose up -d                # start (images already built)
docker compose down                 # stop (volumes preserved)
docker compose logs -f mj-stock-management-api mj-stock-management-frontend # follow logs
docker compose config --quiet       # validate config
```

There is one Compose file — `docker-compose.yml`. It runs only `mj-stock-management-db`,
`mj-stock-management-redis`, `mj-stock-management-api`, `mj-stock-management-frontend`
and `mj-stock-management-telegram-bot` (no RabbitMQ, no Celery workers: scheduled
jobs run inside the API process). To use prebuilt registry images instead of a
local build, set `IMAGE_REGISTRY`, `IMAGE_TAG` and `PULL_POLICY=always` in `.env`.
