# Stock & POS Management System — agent rules

Pharmacy stock + POS: **Nuxt 4 SPA** (`frontend/`, TypeScript, Nuxt UI, Pinia) + **FastAPI modular monolith** (`backend/`, SQLAlchemy 2 async, PostgreSQL, Redis) + Docker Compose. Default shop: Yoeun Sokhon Pharmacy. There is **no root package manifest** — frontend/backend commands target their directory explicitly.

## Documentation map — load ONLY the doc relevant to your task

| Doc | Read it when |
|---|---|
| `docs/PROJECT.md` | project scope, architecture, deployment, non-goals (start here) |
| `docs/FRONTEND.md` | pages, components, config-driven module engine, printing, i18n |
| `docs/BACKEND.md` | modules, config, auth/RBAC, Redis, error contract |
| `docs/DATABASE.md` | tables, migrations, model conventions |
| `docs/BUSINESS_LOGIC.md` | stock/debt/sale/return/finance rules before touching money or stock math |
| `docs/API.md` | endpoint contracts and permissions before changing any API surface |

Never load all six at once. Never recreate removed docs.

## Approved module surface (do not expand)

Dashboard · Stock (Products, Stock Movements) · POS · Delivery Notes · Setup (Categories, Units of Measure, Brands, Suppliers, Customers) · Reports (Sales, Purchases, Customer Debt, Supplier Debt, Finance) · Administration (Users, Roles & Permissions, Document Sequences, Audit Logs, Settings).

No standalone pages/routes for sales, purchases, returns, debts, stock in/adjust/damage/expire, or expenses — those are dialogs, tabs, and report actions.

## Non-negotiables

- Prefer modifying existing code; search for existing components/composables/services/types before creating anything. No duplicates. No broad refactors — keep diffs scoped.
- Frontend CRUD pages are **configuration, not markup**: extend `frontend/app/config/*-modules.ts` / `settings-schemas.ts` (rendered by `ModulePage`/`DocumentView`) before writing custom pages.
- Backend: thin routers; business rules in `app/modules/<m>/service.py`, queries in `repository.py`.
- **Never remove UOM** (`/setup/uoms`, `uoms` module, UOM conversion logic) — required by products, stock, POS, pricing, receipts.
- Preserve API contracts (`/api/v1` envelope, error codes) and business logic unless explicitly requested.
- One canonical stock mutation (`apply_stock_movement`); immutable movements/payments; row-locked sequences and debt settlement; permission checks are server-side (`require_permission`).
- Schema changes get a **new** Alembic revision; never edit an applied migration under `backend/alembic/versions/`.
- Verify imports/references before deleting any file. Delivery Notes is an approved page — analyze its dependency graph before ever proposing removal.
- Known frontend/backend permission-id drift is documented in `BACKEND.md` §8; do not "fix" permissions without explicit approval.

## Setup, run & verify

Load the matching skill in `.opencode/skills/` (`backend`, `frontend`, `database`, `testing`, `project-cleanup`) before non-trivial work.

```bash
cp .env.example .env
pnpm --dir frontend install
python -m pip install -r backend/requirements-dev.txt

docker compose up -d --build            # frontend :80, API :8100, Postgres :55432, Redis :56379
docker compose up -d db redis           # minimum for backend tests
```

Run the smallest relevant check first, then related ones; full suite / frontend build only when required:

```bash
pnpm --dir frontend test -- <file>.spec.ts    # targeted Vitest
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend build                     # slow; only before reporting a frontend task done

python -m pytest backend/tests/modules/<area> -q
python -m pytest backend/tests -q             # full suite (~4 min)

docker compose config --quiet
```

Never report a check as passing unless it ran.
