# Stock & POS Management System — Project Overview

Single-shop pharmacy stock and point-of-sale management system (**Yoeun Sokhon Pharmacy** is the default shop name). It replaced the legacy HollyWing motorcycle-rental app that previously occupied this repository — no rental code, routes, or data remain.

Companion docs (the complete, current set): [FRONTEND.md](FRONTEND.md) · [BACKEND.md](BACKEND.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md) · [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)

## 1. Approved sidebar surface

| Group | Pages |
|---|---|
| — | Dashboard (`/`) |
| — | POS (`/pos`), Delivery (`/delivery-notes`, sidebar label "Delivery"), Stock (`/stock` + `/stock/movements`) — listed in this sidebar order |
| Setup | Categories, Units of Measure (UOM), Brands, Suppliers, Customers (`/setup/*`) |
| Reports | Sales, Purchase, Customer Debt, Supplier Debt, Finance (`/reports/*`) |
| Administration | Users, Roles & Permissions, Document Sequences, Audit Logs, Settings (`/administration/*`) |

There are deliberately **no** separate pages for sales, purchases, returns, debts, stock in, adjustment, damage, expiry, or expenses — those are actions, dialogs, tabs, and report sections. Auth pages live outside the sidebar: Initial Setup (`/auth/setup`, once), Login, Forgot Password (with verify-code step), Reset Password.

## 2. Architecture

Modular monolith, two deployable apps plus infrastructure:

```
┌──────────────────────────┐        /api/v1 (JSON, bearer JWT)
│  Nuxt 4 SPA (frontend/)  │ ───────────────────────────────────►  FastAPI API (backend/)
│  Nuxt UI v4, Pinia,      │                                        ├─ PostgreSQL 16 (authoritative data)
│  ECharts, i18n en/km     │                                        ├─ Redis 7 (transient state only)
└──────────────────────────┘                                        ├─ local disk (product/brand/shop images)
                                                                    └─ in-process asyncio scheduler (daily expiry scan)
                                                                        optional profiles: telegram-bot, queue (off by default)
```

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2 (async), Pydantic v2, Alembic. Thin routers; business rules in `app/modules/<m>/service.py`; queries in `repository.py`. See [BACKEND.md](BACKEND.md).
- **Frontend**: Nuxt 4 / Vue 3 strict TypeScript, Nuxt UI, ECharts (dashboard + finance), Pinia for genuinely shared state only. Most pages are configuration-driven (`app/config/*-modules.ts`). See [FRONTEND.md](FRONTEND.md).
- **Data**: PostgreSQL `NUMERIC` + Python `Decimal` everywhere (money 18,2 · qty 18,4 · factors 18,6). Timestamps UTC, rendered with the configured timezone. Every schema change is an Alembic migration. See [DATABASE.md](DATABASE.md).
- **Core invariants**: one canonical stock-mutation service (`apply_stock_movement`) with row locks and immutable movement ledger; immutable payments/debt settlement with overpayment rejection; row-locked collision-free document sequences; server-side permission checks on every protected endpoint; audit rows committed inside the business transaction. Editing a completed sale/purchase does **not** break these: it appends compensating movements and re-applies the document, then recalculates the linked debt (see [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) §16). See [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md).

## 3. Module map

| Module | Backend (`app/modules/…`) | Owns |
|---|---|---|
| Auth | `auth` | One-time setup, login, JWT rotation, logout revocation, Telegram password reset, profile/avatar, Telegram link codes |
| Administration | `administration` | Users, roles & permissions, permission catalog, document sequences, audit log read API, settings |
| Master data | `categories`, `uoms`, `brands`, `suppliers`, `customers` | Setup CRUD + options; party debt-pay endpoints |
| Stock | `stock` | Products, balances, canonical mutation service, Stock In/Adjust/Damage/Expire, **purchase edit (reverse + reapply)**, purchase returns, sale-price versioning, UOM conversions, batch/FEFO ledger, movements |
| POS | `pos` | Search/barcode, atomic sale completion, **sale edit (reverse + reapply)**, sale returns, receipt payload, HTML printing |
| Delivery Notes | `delivery_notes` | Delivery tracking of sold items (never re-moves stock), status machine, per-sale deliverable items |
| Dashboard | `dashboard` | KPIs, chart series, alerts, recent activity |
| Reports | `reports` | Sales/Purchase/Debt/Finance reports + sale/purchase-return history endpoints + expenses + CSV exports |
| Images | `image` | Local-disk upload + traversal-safe serving |
| Telegram | `telegram` + `shared/telegram` | Expiry alerts, reset-code delivery, payment notifications, view-only inquiry bot |

## 4. Deployment & infrastructure

Lean Compose stack (`infrastructure/docker-compose.yml`): `db` (postgres 16, host port 55432), `redis` (7, host port 56379), `api` (runs `alembic upgrade head` → `python -m app.seed` → uvicorn; host port `API_HOST_PORT:-8100`; media volume `/srv/data/media`), `frontend` (Nuxt static behind nginx, `/api` proxied). **No scheduler, MinIO, or Celery containers by default** — the daily expiry scan runs inside the API process with a Redis NX lock.

```bash
# Compose lives in infrastructure/ (where .env lives); run from the repo root.
powershell -File infrastructure/scripts/init-env.ps1                    # one-time local secrets
docker compose -f infrastructure/docker-compose.yml up -d --build       # dev/first run
docker compose -f infrastructure/docker-compose.yml --profile telegram up -d   # optional view-only inquiry bot
docker compose -f infrastructure/docker-compose.yml --profile queue up -d      # optional RabbitMQ/Celery (dormant code)
docker compose -f infrastructure/docker-compose.yml -f infrastructure/docker-compose.prod.yml up -d   # production (prebuilt GHCR images, fails fast on weak secrets)
```

Production boot refuses: placeholder/short `JWT_SECRET_KEY`, placeholder Telegram client secret, weak `SEED_ADMIN_PASSWORD`, `DEBUG=true`, private-network CORS. `/docs` and `/openapi.json` are disabled in production.

**Windows local deployment**: everything needed sits in `infrastructure/` (compose files, `.env`, launchers). `First Time Setup.bat` generates `.env` with strong random secrets, builds, and starts; `Start Stock POS.bat` / `Stop Stock POS.bat` handle daily use (health-gated start, safe stop). Advanced helpers live in `infrastructure/scripts/stockpos/` (restart, autostart at login, desktop shortcut); logs in `%TEMP%\stockpos-autostart.log`. The local-only overlay binds the app to `127.0.0.1` and never publishes DB/Redis/API to the host. See `infrastructure/README.md`.

**Storage & backups**: PostgreSQL is authoritative; local disk (`LOCAL_STORAGE_DIR`, default `var/media`) holds uploaded images only — no invoice PDFs or export files anywhere. Back up the Compose project's `stock_pos_pgdata` volume (`pg_dump`) and the media volume; Redis is transient. `vercel.json` files exist for an optional static frontend target; the supported path is Compose.

**Infrastructure root**: the Compose files (`.yml`), `.env` templates, launchers, deploy helpers, and host reverse proxies all live in `infrastructure/` (`docker-compose[.local|.prod].yml`, `.env*.example`, `scripts/`, `nginx/`). Service image configs stay next to their build context (`backend/Dockerfile`, `backend/Dockerfile.telegram`, `frontend/Dockerfile` + `nginx.conf`).

## 5. Non-goals (hard exclusions)

- No rentals, motorcycles, fleet, or legacy `/api/v2` surface.
- No S3/MinIO; no invoice/receipt PDF generation, storage, or download — invoices print from browser HTML; no server-stored report exports (CSV is streamed).
- No Docker scheduler or Celery beat in the default stack.
- No standalone pages/routes for sales, purchases, returns, debts, stock operations, or expenses.
- No ERP/ledger, payroll, CRM, e-commerce, multi-company/warehouse, or procurement approvals.
- Telegram: password-reset codes, two expiry-alert windows (90/7 days from settings), view-only inquiry. Secrets server-side; no invoice/payment documents.

## 6. Documented deviations from the original written spec

1. Editing reuses the original transaction screens: Sales Report / customer History rows open the POS in **edit mode** (`/pos?editSaleId=<id>` → `PATCH /pos/sales/{id}`), and Purchase Report / supplier History rows open the Purchase form in **edit mode** (`/reports/purchases/new?editPurchaseId=<id>` → `PATCH /stock/in/{id}`). The Purchase Report Create action routes to the same full-page flow `/reports/purchases/new` (perm `stock.in`). The previous **Return** row actions were removed; the raise-return endpoints (`POST /pos/sales/{id}/return`, `POST /stock/in/{id}/return`) still exist but are not linked from the UI, and there are **no** `/reports/customer-returns` / `/reports/supplier-returns` pages (the `GET /reports/sale-returns` / `GET /reports/purchase-returns` history endpoints remain server-side only).
2. Telegram payment text notifications are implemented (`payment_invoice_notify_enabled`, sale/purchase/daily-summary toggles in Settings), while the original spec said to never send payment text.
3. Known frontend/backend permission-key drift is documented in [BACKEND.md](BACKEND.md) §8 (only `ALL_PAGES` accounts get full UI navigation today; backend enforcement is unaffected).
4. Legacy alias endpoints are kept for compatibility (`/reports/purchases` ≙ `/reports/purchase`; `/auth/forgot-password/verify|reset` ≙ `/auth/verify-reset-code` | `/auth/reset-password`).

## 7. Verification commands

```bash
pnpm --dir frontend test && pnpm --dir frontend typecheck && pnpm --dir frontend lint && pnpm --dir frontend build
python -m pytest backend/tests
docker compose -f infrastructure/docker-compose.yml config --quiet
```

Backend tests need the Compose stack's published ports (Postgres `55432`, Redis `56379`); `tests/conftest.py` creates `stock_pos_test` and runs migrations. CI (`.github/workflows/ci.yml`) runs compose validation, frontend test/typecheck, backend pytest against service containers; `publish-images.yml` publishes `api`, `frontend`, `telegram-bot` images to GHCR.

Known coverage gaps: no dedicated concurrency test for `POST /stock/operations`; the frontend permission-key drift is tested only at the utility level; no e2e/browser tests; no coverage reporting in CI.
