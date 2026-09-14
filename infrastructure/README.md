# Infrastructure — Stock & POS

Everything needed to run Stock & POS in Docker lives in **this folder**:
the Compose files, the `.env` templates, the Windows launchers, and the helper
scripts. The application code stays in `../backend` and `../frontend`; the
Compose files build from those folders.

- `docker-compose.yml` — the **single** stack (PostgreSQL, Redis, API, frontend, Telegram bot).
- `.env.local.example` — template for the local-only run (recommended).
- `Start Stock POS.bat` / `Stop Stock POS.bat` — one-click daily use.
- `First Time Setup.bat` — first run (creates `.env`, builds, starts).
- `scripts/` — PowerShell helpers (see the bottom of this file).
- `nginx/` — optional host reverse-proxy configs.

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
4. Double-click **`Start Stock POS.bat`** (or open <http://localhost>).

In the local-only mode the app binds to **`127.0.0.1:80`**, so it is reachable
from this computer only. PostgreSQL, Redis and the API are **not** published to
the host at all — they stay on the internal Docker network.

## 2. Daily use

| Action | How |
|---|---|
| Start and open the app | double-click `Start Stock POS.bat` |
| Stop safely | double-click `Stop Stock POS.bat` |
| Restart | `scripts\stockpos\restart-system.bat` |
| Start automatically at sign-in | `scripts\stockpos\install-autostart.bat` |
| Desktop shortcut | `scripts\stockpos\install-desktop-shortcut.bat` |
| Remove auto-start | `scripts\stockpos\remove-autostart.bat` |

`Start Stock POS.bat` waits for Docker Desktop and for `GET /health/ready`
(which checks PostgreSQL and Redis) before opening the browser, so it is safe
to double-click right after logging in.

## 3. Configuration (`infrastructure\.env`)

`init-env.ps1` fills the secrets for you. The settings you may change:

| Key | Meaning |
|---|---|
| `FRONTEND_PORT` | host port for the app (default `80`). |
| `FRONTEND_BIND` | `127.0.0.1` = this PC only (default); set a LAN IP or `0.0.0.0` for LAN access. |
| `TELEGRAM_BOT_TOKEN` | optional; leave empty to disable Telegram. |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` | one-time administrator login. |
| `COMPOSE_PROJECT_NAME` | defaults to `stock_pos`; set to `stockmanagement` only to reuse very old volumes. |

> Never commit `.env` — it contains secrets. It is already git-ignored.

### LAN access (optional)
Set `FRONTEND_BIND=0.0.0.0` (or the PC's LAN IP) in `.env`, then
`scripts\stockpos\restart-system.bat`. Add your frontend URL to `CORS_ORIGINS`
if you keep `ENVIRONMENT=production`.

## 4. Data, backups and reset

PostgreSQL data, Redis data and uploaded images live in Docker **named
volumes** (`stock_pos_pgdata`, `stock_pos_redisdata`, `stock_pos_mediadata`) —
they survive `Stop Stock POS.bat` and image rebuilds.

Back up the database:
```powershell
docker compose exec -T db pg_dump -U stock_pos stock_pos > backup.sql
```
Restore:
```powershell
Get-Content backup.sql | docker compose exec -T db psql -U stock_pos stock_pos
```
Uploaded images are in the `stock_pos_mediadata` volume. To erase everything and
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
| Browser shows a connection error | `Start Stock POS.bat`, wait ~1 minute, retry. |
| "Docker is not available yet" | Start **Docker Desktop** and enable *Start Docker Desktop when you sign in*. |
| Port 80 already in use | set `FRONTEND_PORT=8080` in `.env`, then restart. |
| Login fails after setup | the password is in `infrastructure\.env` (`SEED_ADMIN_PASSWORD`). |
| Need logs | `docker compose logs -f frontend api` (run from this folder). |
| Wrong timezone/alerts | check `SCHEDULER_ENABLED` / `EXPIRY_ALERT_SCAN_HOUR` in the API settings. |

## 7. Scripts reference

| Script | Purpose |
|---|---|
| `scripts\init-env.ps1` | Create `.env` with strong random secrets. |
| `scripts\install-client.ps1` / `.sh` | Clone + build + start from source. |
| `scripts\deploy-from-registry.ps1` / `.sh` | Pull prebuilt GHCR images and start (remote prod). |
| `scripts\start-docker.ps1` / `.sh` | Start the **development** stack (`docker compose up -d --build`). |
| `scripts\prepare-production.ps1` | First-time local prep (creates `.env`, cleans caches). |
| `scripts\stockpos\*` | Daily-use helpers behind the `.bat` files. |

Advanced Compose usage (run from this folder, where `.env` lives):
```powershell
docker compose up -d --build        # build images and start
docker compose up -d                # start (images already built)
docker compose down                 # stop (volumes preserved)
docker compose logs -f api frontend # follow logs
docker compose config --quiet       # validate config
```

There is one Compose file — `docker-compose.yml`. It runs only `db`, `redis`,
`api`, `frontend` and `telegram-bot` (no RabbitMQ, no Celery workers: scheduled
jobs run inside the API process). To use prebuilt registry images instead of a
local build, set `IMAGE_REGISTRY`, `IMAGE_TAG` and `PULL_POLICY=always` in `.env`.
