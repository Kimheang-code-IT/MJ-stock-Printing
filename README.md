# MJ Stock Printing — Stock & POS

A stock, printing and point-of-sale management platform built for a printing
business. A modular FastAPI backend runs behind a Nuxt frontend, with PostgreSQL
and Redis, packaged for one-click deployment on Windows with Docker Compose.

> The Compose stack is called **Stock & POS**. This repository holds the MJ
> printing-business deployment of that stack.

## Stack

| Area | Technology |
| --- | --- |
| API | FastAPI, Uvicorn, Pydantic v2, pydantic-settings |
| Data | PostgreSQL (asyncpg), SQLAlchemy 2, Alembic, Redis |
| Background jobs | Celery with the Redis broker |
| Auth | JWT (PyJWT), Argon2 password hashing |
| Frontend | Nuxt, Vue 3, Nuxt UI, Tailwind CSS, Pinia |
| Tables / charts | TanStack Table, Apache ECharts |
| Integrations | Telegram bot, Google Sheets, OpenPyXL, FPDF2 |
| Infrastructure | Docker Compose, nginx, PowerShell / batch launchers |
| Tests | pytest, Vitest, Playwright |

## Repository layout

```text
backend/           FastAPI application (modular monolith)
frontend/          Nuxt application
infrastructure/    Compose files, .env templates, Windows launchers, nginx config
invoice.png        Sample invoice output
AGENTS.md          Agent/contributor guidance for this codebase
```

## Modules

Each business area lives under `backend/app/modules/<name>/`. Shared cross-cutting
helpers live under `backend/app/shared/`, and routers are registered from
`backend/app/api/v1/`.

`administration`, `auth`, `backup`, `brands`, `categories`, `customers`,
`dashboard`, `image`, `pos`, `products`, `reports`, `stock`, `suppliers`,
`uoms`

## Running it

| Script | Purpose |
| --- | --- |
| `First Time Setup.bat` | Creates `.env`, builds images, starts the stack, prints the admin credentials |
| `Start MJ.bat` | Starts the stack for daily use |
| `Stop MJ.bat` | Stops the stack |

The Compose services are `mj-stock-management-db`, `mj-stock-management-redis`,
`mj-stock-management-api`, `mj-stock-management-frontend` and
`mj-stock-management-telegram-bot`.

In local-only mode the app binds to `127.0.0.1:80` and the database, Redis and API
stay on the internal Docker network. `infrastructure/nginx/mj.conf` is a ready-made
HTTPS front for production.

See `infrastructure/README.md` for the full deployment guide.

## Development

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

cd ../frontend
pnpm install
pnpm dev
```
