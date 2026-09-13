# Pharmacy Stock & POS — Project Review Snapshot

> **HISTORICAL SNAPSHOT — superseded.** This review was captured at commit `02f8b2e "update uom"`. Several items below are now outdated (notably: Customer/Supplier detail tabs are **General + History** only; the standalone `/reports/customer-returns` and `/reports/supplier-returns` pages were **removed**; returns now reuse the POS / Purchase screens in **return mode**; the Debt reports have an optional `currency` filter and the party Statement print was removed). For the current state use the companion docs: [PROJECT.md](PROJECT.md) · [FRONTEND.md](FRONTEND.md) · [BACKEND.md](BACKEND.md) · [API.md](API.md) · [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) · [DATABASE.md](DATABASE.md).

> Purpose: one self-contained briefing for an external reviewer (ChatGPT) to judge whether the UI, workflows, frontend, backend, database, API, permissions, stock logic, POS, pricing, batch/expiry, reports, delivery, debt, settings and administration are complete enough for real use.
>
> **Source of truth = current code.** Snapshot taken from working tree at commit `02f8b2e "update uom"` (clean). Docs were used only where they match code; deviations are flagged.
>
> **Legend — status:** `Complete` = implemented end-to-end; `Partial` = works but has gaps; `Needs Review` = implemented but a known issue/uncertainty; `Missing` = not implemented.
> **Assumptions** are marked "(assumption)". Anything unverified is explicitly labelled.

---

## 1. Project Overview

| Item | Value |
|---|---|
| Purpose | Single-shop pharmacy **stock + point-of-sale** management. Default shop name: *Yoeun Sokhon Pharmacy*. Replaced an older motorcycle-rental app; no rental code/routes remain. |
| Frontend | Nuxt 4 SPA (`frontend/`), Vue 3.5 strict TypeScript, Nuxt UI 4, Pinia, TanStack Table, ECharts, Zod, Tailwind 4, `@nuxtjs/i18n` (en/km). `ssr: false`, built as a static site (`nuxt generate`). 47 page files. |
| Backend | FastAPI (`backend/`), Python 3.12, SQLAlchemy 2 async, Pydantic v2, Alembic. Modular monolith (14 modules + shared). |
| Data | PostgreSQL 16 (authoritative), Redis 7 (transient only), local disk for images (no S3/MinIO, no PDF storage). |
| Architecture | Two deployable apps + Compose infra. Browser SPA → `/api/v1` JSON (bearer JWT) → FastAPI services → Postgres/Redis/local disk. Daily expiry scan runs **inside the API process** (no scheduler container). Optional Telegram bot profile. |
| Deployment | `docker compose up -d --build`. API on host `8100`, frontend nginx on host `80`, Postgres `55432`, Redis `56379`. Prod overlay pulls prebuilt GHCR images and fails fast on weak secrets. Windows local helpers under `infrastructure/scripts/stockpos/`. |
| Money/precision | PostgreSQL `NUMERIC` + Python `Decimal` everywhere (money 18,2 · qty 18,4 · factors/rates 18,6); timestamps UTC. |

**Main invariants (enforced in code):**
- One canonical stock mutation: `stock/service.py::apply_stock_movement` (row-locked, immutable ledger).
- Payments / movements / audit rows are append-only.
- Row-locked, gap-free document numbering (`shared/documents/service.py`).
- Server-side permission checks on every protected endpoint (`require_permission`).
- Debt settlement locks the debt row and rejects overpayment; debts inherit the source document currency.
- Delivery Notes never move stock.

---

## 2. Current Module / Page List

Approved sidebar surface (from `AGENTS.md`): Dashboard · Stock (Products, Stock Movements) · POS · Delivery Notes · Setup (Categories, UOM, Brands, Suppliers, Customers) · Reports (Sales, Purchases, Customer Returns, Supplier Returns, Customer Debt, Supplier Debt, Finance) · Administration (Users, Roles & Permissions, Document Sequences, Audit Logs, Settings).

**No standalone routes exist** for sales, purchases, returns, debts, stock in/adjust/damage/expire or expenses — they are dialogs, tabs and report actions.

### 2.1 Core operational pages

| Page / route | Purpose | Main fields / actions | Related API | Status |
|---|---|---|---|---|
| Dashboard `/` | KPI overview | KPI cards (sales, transactions, month sales, pending deliveries, expenses, debts, damage/expiry loss, gross profit), income/expense chart, summary panel, recent activity/top products | `GET /dashboard/summary` | Complete |
| Products list `/stock/products` | Product master + current stock hub | search (barcode-first), filters category/status; columns image, barcode, name, category, brand, UOM, qty, cost, price, nearest expiry, status; row quick-operations dialog (Stock In / Adjustment / Damage / Expiry), QtyHistory dialog; New/Edit/Delete | `GET/POST /products`, `GET/PATCH/DELETE /products/{id}`, `GET /stock/products/{id}/history|batches|cost-history`, `POST /stock/operations` | Complete |
| Product create/edit `/stock/products/new` `[id]` | Product document | Tabs **General** (name, category, image, brand, barcode, base UOM, supplier, status, Track Batch, Track Expiry, FIFO, read-only nearest expiry + Batches panel), **Pricing** (editable UOM conversion/price table + Sale Price History), **Movements** (read-only ledger). Save validation incl. base price > 0 and `normalizeUomConversions`. | `POST/PATCH /products[/{id}]` | Complete (see §7 note on version editing) |
| Stock Movements `/stock/movements` | Immutable movement ledger (read-only) | Columns date, doc no, product, barcode, batch, expiry, type, UOM, qty in/out, balance before/after, user; filter by type | `GET /stock/movements` | Complete |
| POS `/pos` | Two-step selling workspace (full-screen chrome) | Product browser (search/barcode/category), cart (qty, UOM, price, %discount, sale-currency toggle), checkout (customer, outstanding debt, delivery, payment, paid-now), print size dialog, auto-print | `/pos/products/search`, `/pos/products/barcode/{barcode}`, `POST /pos/sales/complete`, `GET /pos/sales/{id}/receipt`, `POST /pos/sales/{id}/return`, `POST /pos/sales/{id}/delivery-notes` | Complete |
| Delivery Notes `/delivery-notes` | Track delivery of sold items (never re-moves stock) | list (no, invoice, customer, phone, location, date, status, items); create from deliverable invoices; detail with status timeline; print | `/delivery-notes` family, `/sales/{id}/deliverable-items`, `/pos/sales/{id}/delivery-notes` | Complete |

### 2.2 Setup (master data CRUD — config-driven)

| Page / route | Purpose | Main fields / actions | Related API | Status |
|---|---|---|---|---|
| Categories `/setup/categories[/new|/{id}]` | Product categories | code, name, description, status, product count; delete guard | `/categories` | Complete |
| Units of Measure `/setup/uoms[/new|/{id}]` | UOM master (required by products/stock/POS/pricing) | code, name, symbol, description, status, product count; disable instead of delete | `/uoms` | Complete |
| Brands `/setup/brands[/new|/{id}]` | Brand master | code, name, logo, description, status, product count | `/brands`, `/images/upload` | Complete |
| Suppliers `/setup/suppliers[/new|/{id}]` | Supplier master + debts | name, phone, location, status; detail tabs debts/purchases/payments; debt payment dialog | `/suppliers`, `/{id}/debts|payments|history`, `/{id}/debts/{debtId}/payments` | Complete (no printed statement — see §10) |
| Customers `/setup/customers[/new|/{id}]` | Customer master + debts | name, phone, location, status; detail tabs debts/purchases/payments; walk-in protected; debt payment dialog | `/customers`, `/{id}/debts|purchase-history|payments`, `/{id}/debts/{debtId}/payments` | Complete (no printed statement — see §10) |

### 2.3 Reports

| Page / route | Purpose | Main columns / actions | Related API | Status |
|---|---|---|---|---|
| Sales `/reports/sales` | Sales line report | invoice, date, customer, cashier, product, qty+UOM, unit price, discount, line total, payment method/status; totals; return dialog; invoice print; CSV | `GET /reports/sales` + `/export`, `POST /pos/sales/{id}/return` | Complete |
| Purchases `/reports/purchases` | Stock-In documents | doc no, date, supplier, item count, total, paid, remaining, status; row detail; **Create** → `/reports/purchases/new`; purchase-return dialog; CSV | `GET /reports/purchase[s]` + `/export`, `POST /stock/in/{id}/return` | Complete |
| Purchase create `/reports/purchases/new` | Full-page Stock In | supplier, document currency/rate, line table (product, UOM, qty, cost, batch selector incl. **+ New Batch**, expiry), header discount/tax, paid → supplier debt; one document for all lines | `POST /stock/in` | Complete |
| Customer Returns `/reports/customer-returns` | Read-only sale-return history | return no, invoice, customer, items, restocked qty, refund, reason, user | `GET /reports/sale-returns` | Complete |
| Supplier Returns `/reports/supplier-returns` | Read-only purchase-return history | return no, purchase, supplier, items, refund, debt reduction, reason, user | `GET /reports/purchase-returns` | Complete |
| Customer Debt `/reports/customer-debts` | Open/partial/paid customer debts | date, invoice, customer, invoice total, paid, remaining, due, status; pay dialog (per-debt + pay-all); CSV | `GET /reports/customer-debts` + `/export`, `/customers/{id}/…/payments` | Complete |
| Supplier Debt `/reports/supplier-debts` | Open/partial/paid supplier debts | date, purchase, supplier, total, paid, remaining, due, status; pay dialog; CSV | `GET /reports/supplier-debts` + `/export`, `/suppliers/{id}/…/payments` | Complete |
| Finance `/reports/finance` | Income/expense ledger + summary | summary cards (sales, purchases, COGS, damage/expiry loss, gross profit, expenses, net); income/expense table; **Add Expense** (perm-gated) | `GET /reports/finance[/summary|/entries]`, `POST /reports/finance/expenses` | Complete |

### 2.4 Administration & auth

| Page / route | Purpose | Main fields / actions | Related API | Status |
|---|---|---|---|---|
| Users `/administration/users[/new|/{id}]` | User management | username, display name, email, role, Telegram username/chat, status, last login; password create-only; enable/disable; admin reset | `GET/POST/PATCH /admin/users`, `POST /admin/users/{id}/reset-password` | Complete |
| Roles & Permissions `/administration/roles[/new|/{id}]` | Role matrix | role name/description + page×action checkbox matrix | `GET/POST/PATCH /admin/roles`, `GET /admin/permissions` | **Needs Review** (frontend/back-end permission-id drift — §13/§17) |
| Document Sequences `/administration/document-sequences[/new|/{id}]` | Numbering config | document type, prefix, padding, year, next-number preview, status | `GET/PATCH /admin/document-sequences` | Complete |
| Audit Logs `/administration/audit-logs` | Read-only audit trail | time, user, event, action, entity, result, IP/device; entity deep-links; filters | `GET /admin/audit-logs` | Complete |
| Settings `/administration/settings` | System settings | rendered groups: **Localization, Stock, Telegram, Security** (schema-driven); Telegram/email test buttons; reset-all-data on Security | `GET/PATCH /admin/settings`, `POST /admin/settings/telegram-test` | **Partial** (schema defines 8 groups; page renders 4 — §13) |
| Auth `/auth/login` `/auth/setup` `/auth/forgot-password` `/auth/verify-code` `/auth/reset-password` | Session & account lifecycle | login; one-time admin setup; Telegram reset code → verify → reset | `/auth/setup/status`, `/auth/setup`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/forgot-password*`, `/auth/verify-reset-code`, `/auth/reset-password`, `/auth/change-password`, `/auth/me`, `/auth/profile/avatar`, `/auth/telegram/link-code` | Complete (reset delivery requires Telegram config) |

**Important dialogs/subpages:** POS checkout panel, POS print-size + currency dialog, outstanding-debt dialog, delivery-info dialog, quick customer create; QtyHistory dialog (Stock-In/Damage add + invoice click-through); Batch list/detail; Sale Price History (+ add version, View Details, version preview); Debt payment; Document return; Document detail; Export dialog; Confirm dialog; Job permission matrix.

---

## 3. Frontend Structure

| Area | Details |
|---|---|
| Pages | `frontend/app/pages/**` — 47 files; one folder per sidebar entry + auth pages. |
| Module engine | **Configuration, not markup.** `app/config/*-modules.ts` (`modules.ts`, `stock-modules.ts`, `admin-modules.ts`, `delivery-modules.ts`) describe path, sidebar group, permission, collection, list columns, form fields/sections, filters, tabs. Rendered by `ModuleWorkspaceView` (list), `ModulePage` → `DocumentView` (create/edit). |
| Document tabs | `utils/module/document-tabs.ts` builds tabs; only `product` and `roles` use custom `documentForm` recipes. `AppDynamicFieldRenderer` maps every `FieldType` (text/select/image/permission-matrix/line-table/uom-conversions/batches/product-movements/sale-price-history/connection-status/notification-rules/…). |
| Shared components | `components/common` (field widgets, dialogs, filters, export), `layout` (header, slidebar, user menu), `module` (page/list/document shells), `document` (form/tab/meta rail), `table` (`AppListTable`, `AppLineTable`), `pos`, `reports`, `stock`, `dashboard`, `settings`. Single dialog shell `CommonAppDialog`. |
| Composables | `useApi` (base URL, bearer, single-flight 401 refresh, 403 re-fetch + alert, cancellation, error normalization), `useAuth`, `useMenu`, `useAppHeader`, `useModule`, `useConfirm`, `useAccessAlert`, `useCurrencyRateDialog`, `useReferenceOptions`, `useGlobalSearch`, `usePosChrome`, `useAppBranding/Localization`. |
| Repositories / adapters | `repositories/contracts` (typed interfaces) + `repositories/http` (real `/api/v1`, snake↔camel adaptation) + `repositories/mock` (in-memory seed). Factory `repositories/index.ts` chooses mode from `public.useMockData`. |
| State | Pinia: `auth.ts` (user/session/`canAccessPage`), `preferences.ts` (theme/locale/currency), `app-data.ts` (per-collection cache + remote CRUD + client query). Genuinely shared state only. |
| i18n | `i18n/locales/en.json` + `km.json` (both ~1,297 lines, key-parity tested). `no_prefix`, default `en`. Label resolution: `labelKey` → scoped → generic → `labelKm`/`label`. |
| Printing | HTML only, browser print dialog (no PDF/S3). `utils/print/`: `html.ts` (A4/A5 iframe), `document.ts` (bilingual chrome), `invoice.ts` (POS receipt, USD/KHR display conversion), `delivery-note.ts`. |
| Mock mode | **Still used and default ON**: `nuxt.config.ts` `useMockData = NUXT_PUBLIC_USE_MOCK_DATA !== 'false'`. `.env.example` and both `vercel.json` set `true`. See risk in §17. |

---

## 4. Backend Structure

| Layer | Details |
|---|---|
| Entry | `app/main.py` (create_app: CORS, `X-Request-ID`, exception handlers, lifespan, router mounting); `app/seed.py` (`python -m app.seed`). |
| API | `app/api/deps.py` (`get_current_user`, `require_permission`, DB session, list params); `app/api/v1/router.py` aggregates `/api/v1`; `app/api/v1/health.py` (`/health`, `/health/live`, `/health/ready`). |
| Modules | `auth, administration, categories, uoms, brands, stock, suppliers, customers, pos, delivery_notes, dashboard, reports, image, telegram`. Standard shape: `models.py / schemas.py / repository.py / service.py / router.py` (pos/reports/dashboard/image have no repository; they query directly). |
| Rules | Thin routers; transactions/business rules in `service.py`; queries in `repository.py`. Errors use a shared envelope + stable codes (`core/exceptions.py`; `core/errors.py` is a compat re-export). `record_audit` and `allocate_document_number` join the caller's transaction and never commit themselves. |
| Auth | HTTPBearer → `decode_token` (type=access, token-version match) → user must be ACTIVE → `request.state.user`. Access 15 min, refresh 7 d, `token_version` invalidation, refresh JTI revocation in Redis. Password reset via Telegram only (hashed code, TTL 5 min, max 5 attempts, 5/h). Rate limit: login 10/min, reset 5/h (refresh limiter defined but **not enforced** — §17). |
| Permissions | Catalog-driven `module.action` strings synced to DB (`core/permissions.py`); wildcard `ALL_PAGES`; `normalize_role_permissions` auto-grants `module.view` and rejects unknown codes; Administrator is a protected system role. Only Administrator is seeded (Cashier/Stock-Staff presets exist but are test-only). |
| Validation | Pydantic v2 (`ge/le/pattern`, `EmailStr`, `AliasChoices`); business errors raise `AppError` subclasses with `field_errors`; `Decimal` + ROUND_HALF_UP quantizers. |
| Background | `core/scheduler.py` in-process daily expiry scan (Redis NX lock) + daily Telegram summary. Optional Celery app/tasks exist but are **dormant** (not used by the running app). Optional Telegram bot (`telegram_bot.py`, `--profile telegram`). Sales/purchase/summary notifications default OFF; expiry alerts/password-reset/inquiry default ON. |

---

## 5. Database Structure

Single linear Alembic chain, **25 revisions, head `0025_sale_price_version_uoms`** (also the applied DB revision). UUID PKs unless noted; money `NUMERIC(18,2)`, qty `NUMERIC(18,4)`, factors/rates `NUMERIC(18,6)`; timestamps `timestamptz` default `now()`.

| Entity | Key columns / relationships / constraints |
|---|---|
| `users` | email unique, password_hash (Argon2), role_id → roles RESTRICT, status, token_version, telegram_chat_id/verified, avatar, last_login_at. |
| `roles` / `permissions` / `role_permissions` | role name unique, `is_system`; permission `code` unique; composite PK join. Role→user RESTRICT. |
| `system_settings` | group_name + `key` unique, jsonb value, `is_secret`, updated_by. |
| `document_sequences` | document_type unique, prefix, next_number, number_length, status. |
| `audit_logs` (append-only) | user_id SET NULL, action, module, entity_type/entity_id, old/new jsonb, ip/ua, created_at. |
| `categories` / `brands` | code unique; brand `logo_object_key`. Products reference category/brand SET NULL. |
| `units_of_measure` | code unique, symbol; **products.uom_id and price UOM rows reference it RESTRICT** (never delete). |
| `suppliers` / `customers` | code unique; customer `is_walk_in`; names indexed. |
| `products` | `barcode` unique NOT NULL, `sku` unique NULL (legacy); category/brand SET NULL, uom RESTRICT; cost/selling price; minimum_stock; `expiry_tracking`, `fifo`, `track_batch`; `uom_conversions` jsonb; image_object_key. |
| `stock_balances` | **PK = product_id**; quantity, average_cost (1:1 materialized total). |
| `batch_stock_balances` | UNIQUE(product_id, batch_no); received/remaining qty; status; unit_cost; expiry_date; **CHECK remaining ≥ 0 and received ≥ remaining**. |
| `stock_transactions` (Stock-In/adjust/damage/expire headers) | document_no unique, type, supplier, discount/tax, currency+exchange_rate, status. |
| `stock_transaction_items` | product RESTRICT; qty/unit_cost/system/actual; batch_no/expiry; entered-UOM snapshot (no FK); `returned_quantity`. |
| `stock_movements` (append-only) | product RESTRICT, type, `quantity_delta`, unit_cost, polymorphic reference_type/reference_id, batch_no, expiry_date, `batch_id` RESTRICT. |
| `product_sale_prices` | product CASCADE; sale_price, effective_date, is_active, version, batch_no, purchase/expiry date; UNIQUE(product,version); **partial unique one-active per (product, COALESCE(batch_no,''))**. |
| `product_sale_price_uoms` (0025) | version CASCADE + uom RESTRICT; factor_to_base, sale_price, is_default_sale; UNIQUE(version, uom). |
| `sales` / `sale_items` | invoice_no unique; customer RESTRICT, cashier RESTRICT; totals/discount/delivery/currency/exchange_rate/payment_status/sale_status. Items keep UOM/name/sku/barcode snapshots + returned_quantity. |
| `sale_item_batches` | sale_item CASCADE + batch RESTRICT; quantity_base, cost_per_base (FEFO allocation record). |
| `sale_returns` / `sale_return_items`, `purchase_returns` / `purchase_return_items` (append-only) | SRT-/PRT- numbers; refund split; restock flag; source-doc links RESTRICT. |
| `payments` (append-only) | payment_no unique; sale/customer/supplier + `customer_debt_id`/`supplier_debt_id` SET NULL; type/method/amount. |
| `customer_debts` / `supplier_debts` | source sale/stock-in RESTRICT; original/paid/remaining; due_date; currency+exchange_rate; status. |
| `delivery_notes` + `delivery_note_sales` (unique note+sale) + `delivery_note_items` | customer RESTRICT; phone/location NOT NULL; status; fulfillment fields; qty ordered/to-deliver/delivered. Never mutates stock. |
| `expenses` | date, category, description, amount, currency+rate, method, created_by. |
| `telegram_expiry_alert_state` | functional unique (product, COALESCE(batch,''), expiry, level). |

**Notable relationships:** product 1:1 balance, 1:N price versions; price version 1:N UOM rows; movement → product/batch; sale → items → batch allocations; debts → source document; payments → debt rows; delivery note ↔ sales (M:N).

**DB-level invariants:** append-only tables (code-enforced, no triggers); one active price version per (product, batch scope); currency never mixed within a document; UOM RESTRICT; unique operational identifiers (barcode, document numbers, sequences).

---

## 6. Stock Logic

| Behavior | As implemented | Status |
|---|---|---|
| Canonical mutation | `apply_stock_movement`: validates type ∈ {STOCK_IN, SALE, SALE_RETURN, PURCHASE_RETURN, ADJUSTMENT_IN/OUT, DAMAGE, EXPIRE} and non-zero delta; row-locks balance (`SELECT … FOR UPDATE`); blocks negative unless `pos.allow_negative_stock`; weighted-average cost on inbound; appends immutable movement; updates balance in caller's transaction. | Complete |
| Stock In | Per line: base UOM or a product pricing row; `base_qty = qty × factor`, `base_cost = cost ÷ factor`; document number `STI-`; header discount (≤ subtotal) + tax; currency + exchange rate; creates movements; supplier required if underpaid → supplier debt; immutable payment rows. | Complete |
| Stock Out | Sales create negative `SALE` movements per line; oversell blocked. | Complete |
| Adjustment | system vs actual quantity, required reason → ADJUSTMENT_IN/OUT at average cost; zero-difference recorded without a movement (`STA-`). | Complete |
| Damage | Positive quantities out at supplied or average cost → DAMAGE (`DMG-`). | Complete |
| Expiry | Same as damage but product must have `expiry_tracking`; may carry batch/expiry → EXPIRE (`EXP-`); loss feeds Finance. | Complete |
| Movement ledger | Append-only; UI adds balance before/after derived from the ledger via a window function (never persisted); movement rows carry batch/expiry/UOM/doc reference/user. | Complete |
| Batch/lot | `batch_stock_balances` keyed by (product, batch_no) with expiry/status/cost/supplier/document; sales allocate `sale_item_batches`; returns restore batches. | Complete |
| Latest batch selection | Purchase create page defaults a new line to the product's **latest non-expired** batch (and its expiry). Outbound flows allocate **FEFO** (earliest expiry first, expired excluded). | Complete |
| New batch auto-generation | **Client-side only** on the Purchase create page: `BATCH-001` incrementing numeric suffix (`generateBatchNo`), skipping taken numbers. The Stock-list quick Stock-In dialog can only pick **existing** lots — it cannot create a new lot. | Partial (see §17) |
| Expiry handling | `products.expiry_tracking` + lot expiry; daily in-process alerts at 90/7-day windows via settings, one per (product, batch, expiry, level); expiry write-off operation. | Complete |
| UOM conversion | Base-UOM mutation; pricing rows carry `factor_to_base`; decimal-safe frontend math (scaled BigInt) mirrors backend `Decimal`; UOM snapshots stored on sale/stock-in lines. | Complete |
| FIFO/FEFO | Two distinct mechanisms: `products.fifo` chooses outbound **cost** from the oldest remaining ledger lots, else weighted average; **batch allocation is FEFO** by expiry. | Complete |

---

## 7. Product Pricing Logic

| Aspect | As implemented | Status |
|---|---|---|
| Product selling price | `products.selling_price` mirrors the POS-active version's default-sale UOM price; the Stock list reads this mirror. | Complete |
| Multiple UOM prices | One **price version** holds N `product_sale_price_uoms` rows (UOM, factor, price, one default-sale). Legacy `products.uom_conversions` jsonb still holds pricing rows used by Stock-In/POS factor lookup. | Complete |
| Price versions | `product_sale_prices`: per product `MAX(version)+1`; effective date; optional batch scope + purchase/expiry dates; created on explicit "Add Version" and automatically when product `selling_price` changes. | Complete |
| Batch-specific versions | Implemented: a version may target one batch/lot; the one-active invariant is per (product, batch scope). | Complete |
| Active/inactive | Exactly one active version per (product, batch scope) via partial unique index; activating deactivates the previous same-scope version and mirrors the price onto `products.selling_price`. | Complete |
| Sale price history (UI) | Table shows Version · Batch/Lot · UOM Prices · Effective Date · Status · Action. Actions: **View Details** (version + batch + purchase date/cost if present + effective + status + all UOM prices with conversion qty), **Activate**, and row-selection that previews the version in the Pricing table (active = editable, old = read-only history). | Complete (newest implementation) |
| POS price resolution | `active_version_uom_prices`: batch-specific active version wins when the cart line has a batch, else the general (batch-less) active version; per UOM; base UOM resolves to `products.selling_price`. | Complete |

**Not fully implemented / limitation:**
- There is **no API to edit an existing version's UOM rows** — only add a new version, activate/deactivate, or change the product's `uom_conversions` (which does not rewrite the version snapshot). Editing the "active version" preview in the Pricing tab therefore updates the product's pricing rows, not the stored version rows. (Marked **Partial**; needs product decision.)

---

## 8. POS Flow

| Step | Behavior |
|---|---|
| Search / barcode | `GET /pos/products/search` (exact barcode short-circuits, then name/SKU/barcode ILIKE, category filter, ≤50, ACTIVE). `GET /pos/products/barcode/{code}` for scanners. |
| Cart | Lines add product with base UOM; switching UOM re-reads price/stock from the pricing row; decimal-safe totals; per-line % discount; editable unit price; sale-currency toggle. |
| Global currency | Each **sale document** records `currency` (USD/KHR) + `exchange_rate` (KHR per 1 USD); all amounts on the sale are in that currency, never mixed. |
| Checkout | Customer (searchable, walk-in default, quick-create), outstanding open debts selectable to settle from tender, delivery capture (phone/location/fee), payment method (CASH / BANK_QR / CUSTOMER_DEBT), paid-now, change. Walk-in cannot take debt; untouched Paid-now pays the full due. |
| Debt | Underpayment creates one `customer_debts` row (`UNPAID`/`PARTIAL`) with optional due date; included open debts are settled oldest-first in the same transaction; overpayment rejected. |
| Delivery | Optional delivery info at checkout creates a Delivery Note via `POST /pos/sales/{id}/delivery-notes` (prefill phone/location). |
| Completion | `POST /pos/sales/complete` — one atomic transaction: permission checks (discount, max-discount setting), FEFO stock-out via canonical mutation, invoice `INV-`, payments, debt, audit; Telegram notify post-commit (best effort). |
| Return | `POST /pos/sales/{id}/return` — pro-rata refund, optional restock (restores original batches + SALE_RETURN movement), reduces the open debt; status `RETURNED`/`PARTIAL_RETURN`. |
| Invoice/receipt | `GET /pos/sales/{id}/receipt` returns print JSON; browser prints HTML (A4/A5, USD/KHR display conversion). No PDF endpoint. |
| Historical currency/rate | Sale stores its currency + exchange rate; reprints use the **stored snapshot**, not the current rate. Print-currency conversion is display-only and never changes recorded amounts. |

---

## 9. Purchase / Stock-In Flow

| Step | Behavior |
|---|---|
| Supplier | Optional; required only when part of the purchase is unpaid (becomes supplier debt). |
| Product selection | Full-page `/reports/purchases/new`; one line per product (duplicate rejected); name-only product picker. |
| Shortcut from Products | Stock list row → quick-operation dialog (Stock In/Adjustment/Damage/Expiry) posts to `POST /stock/operations`; the headless single-product Stock-In selects an **existing** batch/lot. |
| Batch selection | Purchase line batch picker lists existing lots + the row's generated number + **"+ New Batch"**. |
| + New Batch | Generates `BATCH-001`-style number (increment latest numeric suffix, skip taken); created at confirmation. |
| Auto-number | Client-generated (frontend); backend persists the provided `batch_no` and does not auto-number lots. |
| Expiry | Captured per line for expiry-tracked products; required with batch when `expiry_tracking`. |
| Quantity / cost | Entered in a pricing UOM; server converts to base UOM; line total = qty × unit cost. |
| Currency | Document-level USD/KHR + exchange rate; all amounts on that document in one currency. |
| Paid amount | `paid = min(paid, total)`; if `paid < total` a supplier is required and a `supplier_debts` row is created (document currency). |
| Payment | Immutable `Payment` rows (`STOCK_IN_PAYMENT` / `SUPPLIER_DEBT_PAYMENT`). |
| Purchase return | `POST /stock/in/{id}/return` — returnable = qty − returned_quantity; `PRT-`; PURCHASE_RETURN stock-out; reduces the open supplier debt, excess becomes supplier credit. |

**Gap:** quick Stock-In from the Stock list cannot introduce a brand-new batch (existing lots only). New-lot creation lives on the Purchase page. Marked **Partial**.

---

## 10. Customer / Supplier Logic

| Capability | Customer | Supplier |
|---|---|---|
| CRUD | Yes (walk-in row protected from edit/delete). | Yes (auto `SUP-` code). |
| History | Purchase history endpoint + detail tab; payments list. | Stock-In/purchase history endpoint + payments list. |
| Debts | One open debt per sale; inherited currency/rate; list per party. | One open debt per Stock-In document; same rules. |
| Payments | Per-debt (`/{id}/debts/{debtId}/payments`) and party-level pay-all oldest-first (`POST /{id}/payments`); overpayment 422; immutable payments; CDP-/SDP- numbers. | Same pattern. |
| Reports | Customer Debt report + CSV. | Supplier Debt report + CSV. |
| Statements | **No printable account statement / PDF** (visual debt + payments only). | Same. |

---

## 11. Delivery Notes

| Aspect | Behavior |
|---|---|
| Create fields | Customer, phone (required), location (required), optional driver, vehicle, delivery date, fee, received-by, currency, note; lines built from deliverable sale items (qty ordered, qty to deliver ≤ outstanding). |
| Invoice selection | `GET /delivery-notes/deliverable-invoices` → pick one or more sales of one customer → `GET /sales/{id}/deliverable-items`. |
| Status flow | `DRAFT → CONFIRMED → OUT_FOR_DELIVERY → DELIVERED`; `CANCELLED` (reason required); delivered stamps `delivered_at` and sets delivered qty. Legacy status aliases supported. |
| Edit | Draft only (`PATCH`). |
| Permissions | view / create / update / confirm / deliver / cancel. |
| Print | Browser HTML delivery note (`GET /{id}/print`). |
| Relation to POS/customer | POS auto-entry `POST /pos/sales/{id}/delivery-notes`; notes belong to a customer; **stock is never moved** by any transition. |

---

## 12. Reports

All report endpoints support common list params (`q`, `page`, `limit`, `startDate`, `endDate`) plus filters and each money report has a CSV export twin (streamed, not stored). Sales = one row per sale item; Purchase = one row per Stock-In line; Debt = one row per debt document; Finance = summary + income/expense ledger; finance aggregates normalize KHR via each document's stored rate.

| Report | Filters | Main columns | Export | Detail/open | Status |
|---|---|---|---|---|---|
| Sales | customer, status, payment method, dates, q | invoice, date, customer, cashier, product, qty+UOM, unit price, discount, line total, method, status | CSV | Sale return, invoice print | Complete |
| Purchase | supplier, status, dates, q | purchase no, date, supplier, items, total, paid, remaining, status | CSV | Create flow, purchase return | Complete |
| Customer Returns | customer, dates | return no, invoice, customer, items, restocked, refund, reason, user | — | Read-only | Complete |
| Supplier Returns | supplier, dates | return no, purchase, supplier, items, refund, debt reduction, reason, user | — | Read-only | Complete |
| Customer Debt | customer, status, dates | date, invoice, customer, total, paid, remaining, due, status | CSV | Pay (per-debt/pay-all) | Complete |
| Supplier Debt | supplier, status, dates | date, purchase, supplier, total, paid, remaining, due, status | CSV | Pay | Complete |
| Finance | dates | summary cards + income/expense ledger | — | Add Expense | Complete |
| Dashboard | period/date range | KPI cards + chart + alerts + recent activity | — | — | Complete |

---

## 13. Administration

| Area | State |
|---|---|
| Users | Complete — CRUD, role assignment, enable/disable, admin password reset (bumps token_version); last active admin cannot be disabled/demoted. |
| Roles & Permissions | **Needs Review.** Backend catalog is complete and enforced. The frontend matrix/route vocabulary (`categories.*`, `products.*`, `pos.view/operate/export`, `sales.*`, `admin.*`, `settings.app_config.*`) only partially matches backend codes (`category.*`, `stock.view`/`product.*`, `pos.access/discount/debt_sale`, `report.*`, `user.manage`/`role.manage`/`sequence.manage`/`audit.view`/`settings.manage`). The matrix filters out unknown rows (fails closed) and saves can 422 "Unknown permissions". Consequence: only `ALL_PAGES` accounts get full navigation; backend enforcement is unaffected. **Documented — do not "fix" without approval.** |
| Document Sequences | Complete — list + edit prefix/length/next/status; row-locked allocation, self-healing defaults, inactive → 409. |
| Audit Logs | Complete — read-only filtered list with entity deep-links. |
| Settings | **Partial** — `settings-schemas.ts` defines 8 groups (general, localization, email, stock, telegram, notifications, security, system) but `SystemSettingsPage` renders only localization/stock/telegram/security. `appInfoTabs` and `storageSettingsTabs` are defined but unused. Backend `SETTING_GROUPS` covers more keys. |
| RBAC drift | See the Roles row and §17. |

---

## 14. API Summary

Success envelope `{"data": …, "meta": {page,limit,total}?}`; error envelope `{"detail": {code, message, field_errors?}}` with codes `BAD_REQUEST / VALIDATION_ERROR / REFERENCE_NOT_FOUND / CONFLICT / AUTH_REQUIRED / ACCESS_DENIED / RATE_LIMITED`.

| Group | Key endpoints (all under `/api/v1` unless noted) |
|---|---|
| Health | `GET /health`, `/health/live`, `/health/ready` |
| Auth | `GET /auth/setup/status`, `POST /auth/setup`, `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/forgot-password` (+`/verify`,`/resend`,`/reset` aliases), `/auth/verify-reset-code`, `/auth/reset-password`, `/auth/change-password`, `PATCH /auth/profile/avatar`, `POST /auth/telegram/link-code`, `GET /auth/me` |
| Master data | `/categories`, `/uoms`, `/brands`, `/suppliers`, `/customers` — each list/create/options/get/patch/delete; supplier/customer debt & payment sub-routes |
| Products | `GET/POST /products`, `GET/PATCH/DELETE /products/{id}`, `GET/POST /products[/{id}]/sale-prices`, `PATCH /products/sale-prices/{id}`, `POST …/sale-prices/{id}/activate` |
| Stock | `GET/POST /stock/operations`, `POST /stock/in`, `POST /stock/in/{id}/return`, `POST /stock/adjust|damage|expire`, `GET /stock/movements`, `GET /stock/products/{id}/history|batches|cost-history`, `GET /stock/movements/{id}/invoice` |
| POS | `GET /pos/products/search`, `GET /pos/products/barcode/{code}`, `GET/POST /pos/sales`, `POST /pos/sales/complete`, `GET /pos/sales/{id}`, `POST /pos/sales/{id}/return`, `GET /pos/sales/{id}/receipt`, `POST /pos/sales/{id}/delivery-notes` |
| Delivery | `/delivery-notes` list/create/detail/patch/print, `…/confirm|out-for-delivery|deliver|cancel|status`, `GET /delivery-notes/deliverable-invoices`, `GET /sales/{id}/deliverable-items`, `GET /customers/{id}/delivery-notes` |
| Reports | `GET /reports/sales|purchase[s]|customer-debts|supplier-debts|sale-returns|purchase-returns|finance[/summary|/entries]` + `/…/export` CSVs, `POST /reports/finance/expenses` |
| Dashboard | `GET /dashboard/summary` |
| Administration | `GET/POST/PATCH /admin/users`, `POST /admin/users/{id}/reset-password`, `GET/POST/PATCH /admin/roles`, `GET /admin/permissions`, `GET/PATCH /admin/document-sequences`, `GET /admin/audit-logs`, `GET/PATCH /admin/settings`, `POST /admin/settings/telegram-test` |
| Images | `POST /images/upload`, `GET /images/{object_key:path}` |

**Duplicate/alias routes to be aware of:** `POST /pos/sales` vs `/pos/sales/complete`; `…/delivery-notes` registered in both pos and delivery routers; `/reports/purchase` vs `/purchases`; `/reports/finance` vs `/finance/summary`; auth reset aliases.

---

## 15. UI/UX Review Data

> Layout facts are from code; "usability concerns" are observations, not defects unless marked.

### Dashboard — `/`
- **Layout:** KPI card row, income/expense ECharts panel, summary panel, recent activity/top products.
- **Controls:** period switcher + refresh in the header.
- **Concerns:** profit fields are hidden when `dashboard.view_profit` is missing (visual, no message); chart depends on seeded/sale data; no date-picker on the page besides header period.

### Stock / Products list — `/stock/products`
- **Layout:** full-height `AppListTable` with toolbar search + filter menu + actions; row actions menu.
- **Table columns:** image, barcode, name, category, brand, UOM, current qty, cost, sale price, nearest expiry, status.
- **Dialogs:** quick operations (Stock In / Adjustment / Damage / Expiry), quantity history, invoice detail (from a sale movement).
- **Actions:** New product, edit, delete (deactivation-only for master group), row quick-op, open history.
- **Responsive:** toolbar collapses filters behind a mobile button; table scrolls horizontally.
- **Concerns:** quick Stock-In cannot create a **new** batch (existing lots only); a batch-tracked product with no lots cannot be stocked in from this dialog. Product list has no bulk edit/import.

### Product detail — `/stock/products/[id]`
- **Layout:** document shell with tab bar and optional meta rail; wide form for Pricing/Movements.
- **Tabs:** General (identity + Stock Costing + Expiry & Batches), Pricing (UOM table + Sale Price History), Movements (read-only).
- **Controls:** Save/Cancel in header; add/edit pricing rows; add price version; activate; View Details dialog; select version to preview.
- **Concerns:** no cost-history UI although the API/repository exist; editing an active version preview updates product pricing, not the stored version (see §7).

### Stock Movements — `/stock/movements`
- **Layout:** read-only list table; search; type filter; date range.
- **Columns:** date, document no, product, barcode, batch, expiry, type, UOM, qty in/out, balance before/after, user.
- **Concerns:** no export on this page; balance columns are derived and may read as authoritative.

### POS — `/pos`
- **Layout:** full-screen two-step workspace; product browser left, cart right (mobile: stacked); checkout replaces the browser; sidebar and header hidden during checkout.
- **Controls:** search/barcode, category chips, product cards, cart line qty/UOM/price/discount, sale-currency toggle, customer search + quick create, outstanding-debt picker, delivery info, payment method, paid-now, print size + print currency.
- **Dialogs:** customer create, outstanding debt, delivery info, print size.
- **Concerns:** no offline mode; no keyboard-first/quantity hotkeys evident; print depends on browser dialog; large product grids may need pagination/infinite scroll (search caps at 50).

### Purchase create — `/reports/purchases/new`
- **Layout:** schema-driven document page (wide), supplier + currency header, editable line table, totals footer (subtotal/discount/tax/total, paid, remaining).
- **Controls:** product picker (name-only), UOM, qty, cost, batch selector incl. **+ New Batch**, expiry, header discount/tax, paid amount.
- **Concerns:** duplicate product lines rejected; supplier required only when underpaid; batch number is client-generated.

### Delivery Notes — `/delivery-notes`
- **List columns:** delivery no, invoice, customer, phone, location, date, status, items; filters status/customer.
- **Create:** pick customer → deliverable invoices → line qty to deliver → phone/location → submit; auto-print.
- **Detail:** status timeline + transition buttons (permission-gated) + cancel reason + print.
- **Concerns:** delivered quantities auto-fill to full on deliver; partial fulfillment granularity depends on `qty_to_deliver` edits before deliver.

### Setup CRUD (categories/uoms/brands/suppliers/customers)
- **Layout:** generic list + document form; per-entity list columns and fields (see §2.2).
- **Concerns:** supplier/customer detail history tabs are read-only lists; no statement print.

### Reports (sales/purchases/returns/debt/finance)
- **Layout:** list table with filters, totals, row actions (return/pay/detail/open) and export dialog.
- **Concerns:** Finance has no chart by design; Add Expense is a modal only; CSV export is the only file output.

### Administration
- Users/roles/sequences/audit/settings as described in §2.4/§13.
- **Concerns:** Settings page exposes only 4 of 8 schema groups; role matrix is unreliable for non-admin roles (drift).

### Auth
- Centered card layout, locale switch, Telegram reset flow; no social/email login (by design).

---

## 16. Current Tests / Validation

Results below were **actually run during this review** (Windows PowerShell, local Docker db/redis up).

| Check | Command | Result |
|---|---|---|
| Frontend unit tests | `pnpm --dir frontend test` | **33 files / 264 tests passed** |
| Frontend typecheck | `pnpm --dir frontend typecheck` | Passed (no errors) |
| Frontend lint | `pnpm --dir frontend lint` | Passed |
| Frontend build | `pnpm --dir frontend build` (`nuxt generate`) | Passed; 42 routes prerendered (static) |
| Backend tests | `python -m pytest backend/tests -q` | **235 passed in 105.58s** |
| Backend lint | `python -m ruff check app` | **1 error** — `pos/models.py:123 F821 Undefined name 'BatchStockBalance'` (pre-existing) |
| Compose validation | `docker compose config --quiet` | Passed |
| Migration head | `alembic heads` / DB `alembic_version` | `0025_sale_price_version_uoms` (code head = applied head) |

**Test coverage shape**
- Frontend: Node-environment unit/adapter tests only (no DOM library, **no `@vue/test-utils`, no e2e/Playwright/Cypress**).
- Backend: routers/services/DB covered (auth, admin, master data, stock, POS incl. concurrency, returns, delivery, reports/finance, dashboard, telegram, documents, images).
- CI (`.github/workflows/ci.yml`): compose-config validation, `pnpm test` + `pnpm typecheck`, `pytest -q`. **Lint and build are not in CI.**
- Known gaps (docs/PROJECT.md §7): no dedicated concurrency test for `POST /stock/operations`; permission drift tested only at utility level; no coverage reporting.
- Test DB: `tests/conftest.py` creates `stock_pos_test`, runs `Base.metadata.create_all` (not Alembic), seeds, fixed UOM id; requires Postgres `55432` + Redis `56379`.

---

## 17. Known Issues / Risks

**Critical / production-blocking**
1. **Mock mode defaults ON.** `nuxt.config.ts` sets `useMockData = NUXT_PUBLIC_USE_MOCK_DATA !== 'false'`; `.env.example` and both `vercel.json` set `true`, and `frontend/Dockerfile` does **not** pass the flag. A Compose-built frontend therefore runs on in-memory mock data, not the real API, unless `NUXT_PUBLIC_USE_MOCK_DATA=false` is supplied at build. Verify before any real deployment.

**High**
2. **RBAC frontend/backend permission-id drift** (documented): non-`ALL_PAGES` roles have unreliable menu/page visibility; role-matrix saves can 422. Backend enforcement is correct. Do not "fix" without approval.
3. **Quick Stock-In cannot create a new batch** for batch-tracked products (existing lots only) — a real operational gap if staff use the Stock list rather than the Purchase page.
4. **Settings UI is incomplete** vs the schema/backend (only 4 of 8 groups rendered).

**Medium**
5. **No printable customer/supplier statements** (debts/payments only on screen).
6. **Editing an existing sale-price version's UOM rows is not supported** — the UI preview edits product pricing, not the version snapshot (§7).
7. **Backend lint error** `F821 BatchStockBalance` in `pos/models.py` (runtime works via SQLAlchemy registry, but lint fails).
8. **`pytest.ini` has a misplaced `[tool:ruff]` section** (no `pyproject.toml`/`ruff.toml`), so Ruff line-length config is likely not applied.
9. **Dormant/broken backend code:** `tasks/telegram.py::send_payment_invoice` imports a non-existent formatter; `telegram_bot.py` references missing config `settings.telegram_bot_mode`; `shared/telegram/notify.queue_payment_invoice_notify` is a no-op shim; Celery app/tasks unused; `core/money.py` unused; `create_service_token` unused; `telegram.reset.send` permission unused; `rate_limit_refresh_per_minute` defined but `/auth/refresh` is not rate-limited.
10. **Duplicate/alias route registrations** (`/pos/sales` vs `/complete`; `…/delivery-notes` in two routers; report aliases) — risk of divergent schemas/confusion.
11. **`GET /reports/finance/entries` invalid `type` returns a raw `HTTP_422`** (not the structured `VALIDATION_ERROR` envelope).
12. **Model/migration drift:** `TelegramExpiryAlertState.__table_args__` declares a unique constraint that the migration never created (only a functional index exists).
13. **Legacy dual pricing stores:** `products.uom_conversions` JSONB coexists with normalized `product_sale_price_uoms` (0025); both are read today.
14. **`stock_transactions.confirmed_by` is write-only** (never read).
15. **Frontend dead/unused wiring:** `ProductCostHistoryRow` / `listProductCostHistory` / `PRODUCT_COST_HISTORY` have no UI consumer; `appInfoTabs` / `storageSettingsTabs` defined but unused.
16. **Docs drift:** `docs/DATABASE.md` documents 0001–0024 (misses `0025_sale_price_version_uoms`) and misattributes `users.token_version` to migration 0012 (it is in 0001).

**Low / informational**
17. Dashboard profit gating happens in the service (route only checks `dashboard.view`).
18. `products.sku` / `sale_items.sku` are legacy fields retained for snapshots.
19. No e2e/browser tests; no coverage reporting in CI.

---

## 18. Completeness Matrix

| Area | Frontend | Backend | Database | Tests | UI Ready | Production Ready | Notes |
|---|---|---|---|---|---|---|---|
| Dashboard | Complete | Complete | Complete | Complete | Yes | Yes | Profit fields visually gated by `dashboard.view_profit`. |
| Products | Complete | Complete | Complete | Complete | Yes | Yes | Cost-history API exists, no UI. |
| Pricing | Complete | Complete | Complete | Partial | Yes | Yes | No API to edit an existing version's UOM rows. |
| Batch/Expiry | Partial | Complete | Complete | Complete | Partial | Yes | Quick Stock-In can't create a new lot; FEFO + expiry alerts implemented. |
| Stock Movements | Complete | Complete | Complete | Complete | Yes | Yes | Read-only ledger; derived balances. |
| POS | Complete | Complete | Complete | Complete | Yes | Yes | No offline mode; browser print only. |
| Purchases | Complete | Complete | Complete | Complete | Yes | Yes | Client-generated batch numbers. |
| Customers | Complete | Complete | Complete | Complete | Yes | Yes | No printed statement. |
| Suppliers | Complete | Complete | Complete | Complete | Yes | Yes | No printed statement. |
| Delivery Notes | Complete | Complete | Complete | Complete | Yes | Yes | Never touches stock. |
| Reports | Complete | Complete | Complete | Complete | Yes | Yes | CSV export streamed; no stored files. |
| Finance | Complete | Complete | Complete | Complete | Yes | Yes | Derived income + expense ledger. |
| Users | Complete | Complete | Complete | Complete | Yes | Yes | Last-admin guard. |
| Roles & Permissions | Partial | Complete | Complete | Partial | Needs Review | Needs Review | Frontend/backend permission-id drift. |
| Settings | Partial | Complete | Complete | Partial | Partial | Partial | Only 4 of 8 schema groups rendered. |

---

## 19. Questions for ChatGPT Review

Please review this project and tell me:

1. Is the UI/page structure enough for a complete pharmacy stock/POS system?
2. Which pages or workflows are missing?
3. Which existing screens should be simplified or improved?
4. Are stock, batch, expiry, UOM, pricing, POS, purchase, debt, delivery, and report flows logically complete?
5. Which issues are critical before production?
6. Which improvements are optional?
7. Give a prioritized P0/P1/P2 improvement plan.
