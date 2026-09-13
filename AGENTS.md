# Stock & POS Management System — agent rules

Pharmacy stock + POS app: **Nuxt 4 SPA** (`frontend/`, TypeScript, Nuxt UI, Pinia) + **FastAPI modular monolith** (`backend/`, SQLAlchemy 2, PostgreSQL, Redis) + Docker Compose. Default shop: Yoeun Sokhon Pharmacy.

## Documentation map — load ONLY the doc relevant to your task

| Doc | Read it when |
|---|---|
| `docs/PROJECT.md` | project scope, architecture, deployment, non-goals |
| `docs/FRONTEND.md` | pages, components, config-driven module engine, printing, i18n |
| `docs/BACKEND.md` | modules, config, auth/RBAC, Redis, error contract |
| `docs/DATABASE.md` | tables, migrations, model conventions |
| `docs/BUSINESS_LOGIC.md` | stock/debt/sale/return/finance rules before touching money or stock math |
| `docs/API.md` | endpoint contracts and permissions before changing any API surface |

Never load all six at once. Never recreate removed docs.

## Approved module surface (do not expand)

Dashboard · Stock (Products, Stock Movements) · POS · Delivery Notes · Setup (Categories, Units of Measure, Brands, Suppliers, Customers) · Reports (Sales, Purchases, Customer Returns, Supplier Returns, Customer Debt, Supplier Debt, Finance) · Administration (Users, Roles & Permissions, Document Sequences, Audit Logs, Settings).

No standalone pages/routes for sales, purchases, returns, debts, stock in/adjust/damage/expire, or expenses — those are dialogs, tabs, and report actions.

## Non-negotiables

- Prefer modifying existing code; search for existing components/composables/services/types before creating anything. No duplicates.
- No broad refactors. Keep diffs scoped to the task.
- **Never remove UOM** (`/setup/uoms`, `uoms` module, UOM conversion logic) — required by products, stock, POS, pricing, receipts.
- Preserve API contracts (`/api/v1` envelope, error codes) and business logic unless explicitly requested.
- One canonical stock mutation (`apply_stock_movement`); immutable movements/payments; row-locked sequences and debt settlement; permission checks are server-side (`require_permission`).
- Verify imports/references before deleting any file. Delivery Notes is an approved page — analyze its dependency graph before ever proposing removal.
- Known frontend/backend permission-id drift is documented in `BACKEND.md` §8; do not "fix" permissions without explicit approval.

## Verification

Run the smallest relevant check first (see the `testing` skill), then related ones. Only run the full suite when required:

```bash
pnpm --dir frontend test | typecheck | lint | build
python -m pytest backend/tests          # needs docker compose up -d db redis
docker compose config --quiet
```

Never report a check as passing unless it ran.
