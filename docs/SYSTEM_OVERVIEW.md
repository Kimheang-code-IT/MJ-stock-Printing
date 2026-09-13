# System Overview — Pharmacy Stock & POS Management System

> Documentation generated from the actual implementation (`backend/`, `frontend/`, `docker-compose.yml`, `backend/alembic/`), not from plans. Companion files: [FRONTEND.md](FRONTEND.md) · [BACKEND.md](BACKEND.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md) · [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) · [RBAC.md](RBAC.md) · [REPORTS.md](REPORTS.md) · [SYSTEM_FLOW.md](SYSTEM_FLOW.md) · [INFRASTRUCTURE.md](INFRASTRUCTURE.md) · [DEPLOYMENT.md](DEPLOYMENT.md) · [TESTING.md](TESTING.md)

## 1. What the system is

A single-shop pharmacy stock and point-of-sale management system ("Yoeun Sokhon Pharmacy" is the default shop name in settings). It replaces the legacy HollyWing motorcycle-rental app that previously occupied this repository.

The sidebar surface is exactly:

| Group | Pages |
|---|---|
| — | Dashboard (`/`) |
| — | Stock (`/stock`), POS (`/pos`), Delivery Notes (`/delivery-notes`) |
| Setup | Categories, Units of Measure (UOM), Brands, Suppliers, Customers (`/setup/*`) |
| Reports | Sales, Purchase, Customer Returns, Supplier Returns, Customer Debt, Supplier Debt, Finance (`/reports/*`) |
| Administration | Users, Roles & Permissions, Document Sequences, Audit Logs, Settings (`/administration/*`) |

There are deliberately **no** separate pages for sales, purchases, debts, stock in, adjustment, damage, expiry, or expenses. Those are actions, dialogs, tabs and report sections (see [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)). Returns have read-only **history report pages** (`/reports/customer-returns`, `/reports/supplier-returns`); the return actions themselves stay dialogs on the Sales/Purchase reports.

## 2. Architecture

Modular monolith, two deployable apps plus infrastructure:

```
┌──────────────────────────┐        /api/v1 (JSON, bearer JWT)
│  Nuxt 4 SPA (frontend/)  │ ───────────────────────────────────►  FastAPI API (backend/)
│  Nuxt UI v4, Pinia,      │                                        ├─ PostgreSQL 16 (authoritative data)
│  ECharts, i18n en/km     │                                        ├─ Redis 7 (transient state only)
└──────────────────────────┘                                        ├─ local disk (product/brand/shop images)
                                                                    └─ in-process asyncio scheduler (daily expiry scan)
                                                                        optional: telegram-bot profile, Celery/queue profile (off by default)
```

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2 (async, asyncpg), Pydantic v2, Alembic. Route handlers are thin; business rules live in `app/modules/<m>/service.py`; DB access in `repository.py`.
- **Frontend**: Nuxt 4 / Vue 3 / strict TypeScript, Nuxt UI, ECharts (dashboard + finance chart only), Pinia only for genuinely shared state (auth session, preferences, cached option lists). Most pages are **configuration-driven** (`app/config/*-modules.ts` rendered by generic `ModulePage` / `WorkspaceView` / `DocumentView` components); POS, Delivery Notes, Dashboard and Reports have dedicated pages.
- **Money/quantities**: PostgreSQL `NUMERIC` + Python `Decimal` everywhere; `Numeric(18,2)` for money, `Numeric(18,4)` for quantities, `Numeric(18,6)` for UOM factors and exchange rates. Timestamps stored UTC (`DateTime(timezone=True)`), rendered with the configured system timezone.
- **Document currency**: every money document (Stock In, sale, expense, debt) records the currency it was captured in (`USD` | `KHR`) plus `exchange_rate` (KHR per 1 USD; 1 for USD documents). All amounts on a document are in that currency — never mixed. Debts inherit their source document's currency so payments stay in the same currency; the Finance report normalizes KHR rows to USD via the stored rate. Printing may convert to a different currency (display-only), but recorded amounts never change.
- **API contract**: all Stock & POS endpoints under `/api/v1`, JSON envelope `{"data": ..., "meta": {...}}`, stable error codes (`VALIDATION_ERROR`, `REFERENCE_NOT_FOUND`, `CONFLICT`, `AUTH_REQUIRED`, `ACCESS_DENIED`, `RATE_LIMITED`), `X-Request-ID` echo on every response.

## 3. Module map

| Module | Backend (`app/modules/…`) | Owns |
|---|---|---|
| Auth | `auth` | Initial setup (once), login, JWT access/refresh rotation, logout + revocation, password reset via Telegram codes, change password, profile/avatar, Telegram link codes |
| Administration | `administration` | Users, Roles & Permissions, permission catalog, Document Sequences, Audit Log read API, System Settings (grouped key/value) |
| Master data | `categories`, `uoms`, `brands`, `suppliers`, `customers` | Setup CRUD + option endpoints; customer/supplier debt pay endpoints |
| Stock | `stock` | Products, stock balances, canonical stock-mutation service, Stock In / Adjustment / Damage / Expire, purchase returns, sale-price versioning, UOM conversions, cost history, movements |
| POS | `pos` | Product search/barcode, atomic sale completion, sale returns, receipt payload, browser/OS HTML printing |
| Delivery Notes | `delivery_notes` | Delivery tracking of sold items (never re-moves stock), status machine, per-sale deliverable items |
| Dashboard | `dashboard` | KPI summary + chart series + stock alerts + recent activity |
| Reports | `reports` | Sales / Purchase / Customer Returns / Supplier Returns / Customer Debt / Supplier Debt / Finance (+ expenses, exports) |
| Images | `image` | Upload + serve product/brand/shop images from local disk |
| Telegram | `telegram` + `shared/telegram` | Expiry alert scan/state, password-reset delivery, payment notifications, view-only stock inquiry bot |

## 4. Core concepts

- **Canonical stock mutation** — `apply_stock_movement()` in `stock/service.py` is the only code that changes `stock_balances`. It locks the balance row (`SELECT … FOR UPDATE`), rejects insufficient stock unless `pos.allow_negative_stock` is on, appends an immutable `stock_movements` row, and updates the materialized balance in the caller's transaction. Every flow (stock in, adjustment, damage, expiry, POS sale, sale return, purchase return) goes through it.
- **Base-UOM accounting** — products have one base UOM plus optional pricing rows (`uom_conversions` JSONB). Lines are entered in a selected pricing UOM with `factor_to_base`; stock is always mutated in the base UOM (`qty × factor`), while `uom_symbol` snapshots preserve display.
- **Versioned sale prices** — `product_sale_prices` keeps one POS-active row per product (partial unique index). Editing `selling_price` on a product adds + activates a new version in the same transaction, so POS can never diverge from the Stock list.
- **Average cost** — `stock_balances.average_cost` is a weighted average recomputed on every `STOCK_IN`; it feeds COGS, adjustment/damage/expiry valuation, and sale-item `unit_cost`.
- **Document sequences** — every business document number comes from `document_sequences` (`allocate_document_number`, row-locked, gap-free per allocation, collision-free under concurrency): `INV`, `SRT`, `PRT`, `STI`, `STA`, `DMG`, `EXP`, `DN`, `CUS`, `SUP`, `CDP`, `SDP`.
- **Immutable transactions** — payments, stock movements, audit logs and returns are append-only; debts are updated only inside the same transaction that inserts the payment, with row locks and overpayment rejection.
- **RBAC** — permission codes `module.action` (catalog in `core/permissions.py`), one wildcard `ALL_PAGES` for the Administrator system role; enforced server-side on every protected endpoint via `require_permission(...)`; the frontend only mirrors checks for UX. **Known frontend/backend permission-key drift is documented in [RBAC.md](RBAC.md) §5.**

## 5. Business workflows at a glance

Full detail in [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) / [SYSTEM_FLOW.md](SYSTEM_FLOW.md):

1. **Purchase → Stock In** (`POST /stock/in`): sequence `STI-…`, lines in pricing UOM, supplier optional, document currency (`USD`/`KHR` + exchange rate) and header discount/tax (`total = subtotal − discount + tax`, discount cannot exceed the subtotal); underpayment requires a supplier and creates `supplier_debts` + `SDP` payment in the document currency; average cost updates; audit row.
2. **Supplier return** (`POST /stock/in/{id}/return`): `PRT-…`, validates returnable qty, stock OUT via `PURCHASE_RETURN`, reduces the purchase's open supplier debt or records a supplier credit.
3. **POS sale** (`POST /pos/sales/complete`): `INV-…`, one atomic transaction = sale + items + payment(s) + optional customer debt (`CDP` settlement of included open debts) + stock movements + sequence + audit, all recorded in the sale's document currency. Discounts gated by `pos.discount` and the `pos.maximum_discount` setting; walk-in customers cannot take debt.
4. **Sale return** (`POST /pos/sales/{id}/return`): `SRT-…`, pro-rata refund, optional restock (`SALE_RETURN` movement), reduces the sale's open customer debt, sale becomes `PARTIAL_RETURN`/`RETURNED`.
5. **Customer/Supplier debt payments** (`POST /customers/{id}/debts/{debtId}/payments`, `…/suppliers/…`): immutable `Payment`, overpayment rejected, status `UNPAID → PARTIAL → PAID`.
6. **Delivery Notes**: created from completed sales (many invoices of one customer per note), status `DRAFT → CONFIRMED → OUT_FOR_DELIVERY → DELIVERED` / `CANCELLED`, tracks `qty_to_deliver/qty_delivered` only — **no second stock-out**.
7. **Finance report**: income derived read-only from POS sales; expenses are user rows (`expenses`) created from the Finance page's Add Expense modal; net result = gross profit − damage loss − expiry loss − operating expenses.
8. **Audit logs**: every meaningful action appends to `audit_logs` inside the same transaction (login failures included).

## 6. Non-goals (hard exclusions, per AGENTS.md / spec)

- No rentals, motorcycles, fleet, or legacy `/api/v2` surfaces.
- No S3/MinIO; images live on local disk. No invoice/receipt PDF generation, storage, or download — POS invoices print from HTML in the browser/OS (the former PDF archive was removed in migration `0017_drop_invoice_pdf_object_key`). No report exports stored server-side (CSV is streamed).
- No Celery beat / Docker scheduler in the default stack; expiry alerts run inside the API process.
- Telegram never receives invoice/payment *documents*; secrets stay server-side. (Note: text notifications of paid sales are implemented — see [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) §9 and the deviations list in §11.)

## 7. Documented deviations from the written spec

The implementation is newer than parts of the spec; these differences exist in code today:

1. **Two extra report pages**: the Reports sidebar includes read-only **Customer Returns** (`/reports/customer-returns`) and **Supplier Returns** (`/reports/supplier-returns`) history pages, and the Purchase Report's Create action routes to a full-page purchase flow (`/reports/purchases/new`, perm `stock.in`). Both are extensions beyond the original page allowlist (returns were dialog-only actions).
2. **Telegram payment text notifications are implemented** (`telegram.payment_invoice_notify_enabled`, `queue_payment_invoice_notify` for CASH/BANK_QR sales and debt payments), while the spec says never to send payment text over Telegram.
3. **RBAC key drift** between the frontend permission matrix and the backend catalog (functional impact described in [RBAC.md](RBAC.md) §5).
4. Legacy alias endpoints are kept for compatibility (`/reports/purchases` ≙ `/reports/purchase`; `/auth/forgot-password/verify|reset` ≙ `/auth/verify-reset-code` | `/auth/reset-password`).

## 8. Verification commands

```bash
pnpm --dir frontend test && pnpm --dir frontend typecheck && pnpm --dir frontend lint && pnpm --dir frontend build
python -m pytest backend/tests
docker compose config --quiet
```

CI (`.github/workflows/ci.yml`) runs compose validation, frontend test/typecheck, and backend pytest against service containers; `publish-images.yml` publishes `api`, `frontend`, `telegram-bot` images to GHCR.
