# Backend — FastAPI application (as implemented)

## 1. Layout

```
backend/app/
├── main.py                 # create_app, CORS, X-Request-ID middleware, lifespan
├── seed.py                 # python -m app.seed (container bootstrap)
├── core/                   # config, database, redis, security, permissions,
│                           # exceptions, errors (compat re-export), logging,
│                           # rate_limit, money, scheduler
├── api/
│   ├── deps.py             # get_db_session, get_current_user, require_permission,
│   │                       # list_params, envelope re-exports
│   └── v1/router.py        # /api/v1 aggregation of all module routers
├── modules/                # one folder per domain: models / schemas / repository /
│   │                       # service / router
│   ├── auth, administration, categories, uoms, brands, stock, suppliers,
│   ├── customers, pos, delivery_notes, dashboard, reports, image, telegram
├── shared/
│   ├── audit/              # AuditLog model + record_audit (no commit)
│   ├── documents/          # DocumentSequence model + allocate_document_number
│   ├── pagination/params.py# ListParams, envelope(), list_meta(), parse_date_range
│   └── telegram/           # client, delivery, inquiry, linking, notify
└── tasks/, telegram_bot.py # optional Celery app + standalone bot (profile-gated, off by default)
```

Rules enforced throughout: routers thin; services own transactions/commit; repositories own queries; `record_audit` and `allocate_document_number` join the caller's transaction and never commit themselves.

## 2. Configuration (`core/config.py`, Pydantic settings)

Key settings (env-prefixed upper-case): `DATABASE_URL` (asyncpg), `REDIS_URL`, `JWT_SECRET_KEY` (HS256), `ACCESS_TOKEN_EXPIRE_MINUTES=15`, `REFRESH_TOKEN_EXPIRE_DAYS=7`, `SERVICE_TOKEN_EXPIRE_MINUTES=10`, `TELEGRAM_*` (bot token, client id/secret, reset code 5 min, max 5 attempts, link code 10 min), `FRONTEND_BASE_URL`, `EXPIRY_ALERT_SCAN_HOUR=7` (UTC), `SCHEDULER_ENABLED=true`, `CORS_ORIGINS`, `CORS_ALLOW_PRIVATE_NETWORKS` (dev only), rate limits (login 10/min, refresh 30/min, reset 5/h), `SEED_ADMIN_*`, `DEFAULT_PAGE_SIZE=20`, `MAX_PAGE_SIZE=100`, `LOCAL_STORAGE_DIR=var/media`, `MAX_UPLOAD_BYTES=5MB`.

`assert_safe_for_production()` **refuses to boot** in `ENVIRONMENT=production` when: JWT secret is a placeholder or < 32 chars, Telegram client secret placeholder, seed admin password weak/placeholder, `DEBUG=true`, or private-network CORS allowed.

## 3. Request pipeline

1. **CORS** — allow-list origins; `allow_credentials=False` (bearer tokens, no cookies for auth). In development, a regex additionally allows LAN origins (192.168/10/172.16–31/localhost).
2. **`X-Request-ID`** middleware — echoes or generates a request id on every response.
3. **Exception handlers** map app errors to a stable envelope (see §6).
4. **Auth** — `HTTPBearer` → `decode_token` (type=access, version match) → `UserRepository.get_by_id` → status must be `ACTIVE` → `request.state.user`.
5. **Authorization** — `require_permission("module.action")` dependency; `ALL_PAGES` bypasses.

## 4. Module notes

### auth
- `GET /auth/setup/status`, `POST /auth/setup` (allowed **once** — any existing user blocks it; syncs permission catalog, creates Administrator role, audits `initial_setup`).
- `POST /auth/login` — rate limited per `ip:email`; failed attempts audited; issues access (15 min) + refresh (7 d) JWTs carrying `ver = token_version`.
- `POST /auth/refresh` — rotation; `POST /auth/logout` — revokes refresh JTI in Redis (`revoked:jti`, TTL = remaining lifetime).
- Password reset via Telegram: `forgot_password` → 6-digit code hashed in Redis state (TTL 5 min, max 5 attempts, 5/hour rate limit) → `verify_reset_code` returns short-lived reset token → `reset_password` bumps `token_version`. Alias routes `/forgot-password/verify|reset|resend|handoff` exist for the SPA flow (handoff exchanges a one-time token for a token pair).
- `POST /change-password` (verifies current), `PATCH /profile/avatar`, `POST /telegram/link-code`, `GET /auth/me`.

### administration
- Users CRUD-ish (`GET/POST /users`, `PATCH /users/{id}`, `POST /users/{id}/reset-password`) — cannot disable/demote the last active admin; password resets bump `token_version` and audit.
- Roles: list/create/update with `normalize_role_permissions` (unknown codes → 422; non-view actions auto-grant `module.view`; Administrator must keep `ALL_PAGES`; system roles cannot be renamed/disabled; disabling blocked while users exist).
- `GET /permissions` — the catalog the role matrix renders.
- Document sequences: list + PATCH (prefix/number_length/next_number/status).
- Audit logs: filterable read-only list.
- Settings: `GET /settings` (secrets masked), `PATCH /settings` (validated against the `SETTING_GROUPS` catalog, audit on change).

### stock (largest module)
- **ProductService** — CRUD with barcode-first identity (barcode unique + required, auto-issued `BAR-…` when omitted; `sku` optional legacy code, unique when set), category/UOM/brand validation (UOM required + ACTIVE), `uom_conversions` normalization/validation, delete guards (no movements, zero balance), sale-price version creation on `selling_price` change, cost-price audit (`price_changed`).
- **`apply_stock_movement`** — the canonical mutation (see [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) §1): locks balance, optional negative-stock check (`pos.allow_negative_stock`), weighted-average cost on `STOCK_IN`, immutable movement row.
- **StockOperationService** — `stock_in` (UOM factor validation, base-UOM conversion, document currency `USD`\|`KHR` + exchange rate, header discount ≤ subtotal and tax → `total = subtotal − discount + tax`, supplier debt creation when underpaid — in the document currency, `SDP`/`STOCK_IN_PAYMENT` payment rows), `update_purchase` (`PATCH /stock/in/{id}`, perm `stock.in` — edits a `CONFIRMED` Stock In with no purchase returns: deducts each original line's batch and appends compensating `PURCHASE_RETURN` movements, deletes the old items, re-applies the new lines, rewrites header totals/currency/rate and recalculates the linked `SupplierDebt` from the new total; immutable payments kept, audited `stock_in_update`), `purchase_return` (deducts the **original batch lot** of each returned line — or FEFO for unbatched lines — and writes the PRT document), `adjust` (system vs actual quantity; ADJUSTMENT_IN/OUT), `damage`, `expire` (requires `expiry_tracking`), `quick_operation` (single-product dialog on the Stock list), `list_operations` (purchase list read model), `list_movements` (read-only ledger for the Stock Movements page: q/product/type/date filters, pagination, `sort`; rows enrich the immutable movement with product barcode, qty in/out and balance before/after — the balances are computed from the ledger with a window function, never persisted), product history (`stock/history.py`), cost history.
- **Sale prices** (`stock/sale_prices.py`) — versioned price list/add/patch/activate; each version holds per-UOM price rows (`product_sale_price_uoms`) and an optional batch scope; exactly one active version per product + batch scope (batch-specific active version wins over the general one), and the active default-sale UOM price mirrors onto `products.selling_price` in the same transaction.

### pos
- `search_products` (exact barcode match short-circuits to one product, then name/SKU/barcode ILIKE, category filter, max 50, ACTIVE only), `product_by_barcode`.
- **`complete_sale`** — see [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) §3 for the full atomic flow (discount permission + max-discount settings, document currency `USD`\|`KHR` + exchange rate recorded on the sale with debts inheriting it, walk-in debt guard, included-debt settlement, change calculation, Telegram notify is post-commit best effort).
- `return_sale` — pro-rata refunds, restock via `SALE_RETURN` restoring the **original sold batches** (newest allocation first), debt reduction, `sale_status` transitions. Endpoint kept; the POS return mode preload (`GET /pos/sales/{id}`) now powers **edit** instead.
- **`update_sale`** (`PATCH /pos/sales/{id}`, perm `pos.access`) — edits a `COMPLETED` sale that has **no returns**: locks the sale, reverses each original line (restores its batches and appends compensating `SALE_RETURN` movements — the old `SALE` rows are never mutated), deletes the old `SaleItem`s, re-applies the new lines (same UOM/discount/batch rules as `complete_sale`), rewrites header totals/currency/rate, and recalculates the linked `CustomerDebt` from the new grand total. Recorded `Payment` rows are immutable, so the already-paid amount stands (`paid_for_sale = min(existing_paid, grand_total)`). Audited as `sale_update`.
- `build_receipt` — bilingual JSON print payload (shop settings, timezone-aware dates, customer phone/address, document `currency` + `exchange_rate`, paper size, exchange-rate display flag, footer, items with UOM/qty/unit price/discount/line total, totals incl. delivery fee, paid/debt/change, last payment method).

### delivery_notes
- Deliverable-item computation per sale (ordered − already-on-note − delivered), multi-invoice notes for one customer, draft editing, strict status machine with required phone/location before Confirm/Out/Deliver, cancellation reason required, `qty_delivered` set on Deliver, print payload endpoint, per-customer note list. Audit on every transition.

### customers / suppliers
- CRUD with code auto-allocation, delete guards (in-use parties rejected with Conflict), debt lists, purchase/supply history, payment history.
- **Debt payment** (both parties): locks the debt row, rejects overpayment (422), inserts immutable `Payment`, updates `paid/remaining/status`, audits, then best-effort Telegram notify. `pay_open_debts` settles oldest-first in one transaction.

### dashboard
`GET /dashboard/summary?period=&startDate=&endDate=` — sales stats, this-month sales, pending deliveries, operating expenses (excludes purchase cost), customer/supplier debt totals, damage/expiry losses, refunds, COGS, chart series, low-stock + expiring counts (vs `minimum_stock` and expiry windows), recent sales/stock activity, top products. Cached briefly in Redis (60 s TTL).

### reports
Sales / Purchase / Customer Debt / Supplier Debt / Sale-Return / Purchase-Return reports with server-side filters + CSV export; the two debt reports accept an optional `currency` filter (USD \| KHR, never mixed). Finance report (summary + income/expense entries + `POST /finance/expenses` gated by `report.finance` **and** `expense.create`). Finance aggregates normalize document currency via `exchange_rate` (KHR rows ÷ rate; damage/expiry losses come from the movement cost ledger and stay as recorded). Formulas in [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) §14.

### image
`POST /images/upload` (multipart, 5 MB cap, image content types, per-folder object naming on local disk) and `GET /images/{object_key:path}` (path-traversal-guarded via `_safe_segment`/resolved-path check).

### telegram
`ExpiryAlertService.scan_and_send` — daily in-process sweep (settings windows 90/7 days, once-per-lot state, Redis NX lock); `shared/telegram` holds the HTTP client, reset-code delivery, payment notify queue, and the view-only inquiry bot (`telegram_bot.py`, optional `telegram-bot` compose profile).

## 5. Redis usage (transient only)

| Key pattern | Purpose |
|---|---|
| `ratelimit:{key}:{window}` | INCR/EXPIRE sliding counters (login, refresh, reset). Redis down ⇒ fail open |
| reset-code state (hashed code, attempts, expiry) | password-reset flow |
| `revoked:jti` | refresh-token revocation |
| dashboard/settings cache | short-lived read caches (60–120 s) |
| `stock_pos:scheduler:expiry_scan` | NX lock so multiple API workers don't double-scan |

## 6. Error contract

All errors return `{"error": {"code", "message", "field_errors?"}}`-style payloads with codes: `VALIDATION_ERROR` (422, includes `field_errors`), `REFERENCE_NOT_FOUND` (404), `CONFLICT` (409), `AUTH_REQUIRED` (401), `ACCESS_DENIED` (403), `RATE_LIMITED` (429), `BAD_REQUEST` (400). Success responses use `{"data": …, "meta": {"page","limit","total"}?}`. `/docs`, `/redoc`, `/openapi.json` are disabled in production.

## 7. Scheduler

`core/scheduler.py` starts an asyncio task inside the API process (gated by `SCHEDULER_ENABLED`); it sleeps until `EXPIRY_ALERT_SCAN_HOUR` UTC, takes a Redis NX lock, then runs `ExpiryAlertService.scan_and_send()`. No Docker scheduler, no Celery beat. Errors are logged and retried the next day; delivery failures leave alert state unwritten so the next sweep retries.

## 8. RBAC — permission model (catalog, enforcement, known drift)

**Model**: permission rows are catalog-driven `module.action` strings synced into the `permissions` table by `build_all_permissions()` (on setup, on `app.seed`, and on Administrator creation); one wildcard `ALL_PAGES`. Role 1—N RolePermission; users have exactly one role; `roles.is_system` protects Administrator (cannot rename, disable, or strip `ALL_PAGES`). Granting any non-view action auto-grants the module's `view` (`normalize_role_permissions`); an Administrator with `ALL_PAGES` collapses to the wildcard.

**Backend catalog** (`app/core/permissions.py`):

| Module | Actions |
|---|---|
| dashboard | view, view_profit |
| category / uom / brand | view, create, update, delete |
| stock | view, in, adjust, damage, expire |
| product | create, update, delete |
| supplier | view, create, update, delete, debt.pay |
| pos | access, discount, debt_sale, print |
| customer | view, create, update, delete, debt.pay |
| delivery | view, create, update, confirm, deliver, cancel |
| report | sales, purchase, customer_debt, supplier_debt, finance |
| expense | create (Add Expense on the Finance report only) |
| user / role / sequence | manage |
| audit | view |
| settings | manage |
| service-only (non-assignable) | telegram.reset.send |

**Enforcement**: every protected endpoint declares `Depends(require_permission("module.action"))` — see the permission column in [API.md](API.md). `require_permission` chains `get_current_user` (active account + token version) then `user_has_permission` (`ALL_PAGES` or exact code) → 403 `ACCESS_DENIED`. Read endpoints are also gated (e.g. `stock.view`, `report.*`, `audit.view`). Object-level IDOR guards: debts must belong to the path customer/supplier; included debts must belong to the sale's customer; delivery notes are only created from real sales; images are path-traversal-guarded; the last active admin cannot be demoted; the walk-in customer cannot take debt. Seeded presets: **Administrator** (`ALL_PAGES`, system), plus code-defined **Cashier** and **Stock Staff** presets used by tests/seeding helpers.

**⚠️ Known frontend/backend permission-key drift** (documentation-first finding, no functional backend impact): the frontend role matrix and route guards use their own vocabulary that only partially matches the backend catalog — `categories.*` vs `category.*`, `products.*` vs `stock.view`/`product.*`, plural `suppliers.*`/`customers.*`, `pos.view/operate/export` vs `pos.access/discount/debt_sale`, `sales.*`/`reports.*` vs `report.*`, `admin.*`/`configuration.*`/`settings.app_config.*` vs `user.manage`/`role.manage`/`sequence.manage`/`audit.view`/`settings.manage`. Consequences: menu/page visibility for non-admin roles is unreliable (mismatched matrix rows are filtered out and fail closed; `useMenu` ids like `products.view` never match `stock.view`), and saving a role from the frontend matrix can be rejected (422 "Unknown permissions"). Only `ALL_PAGES` accounts experience full navigation today; backend enforcement is unaffected and remains authoritative. A fix would map matrix rows ↔ catalog codes (or regenerate the matrix from the catalog) and align `useMenu`/`definePageMeta` ids. **Partial fix in place**: the matrix renders the live backend catalog (`GET /admin/permissions`) and falls back to the frontend mirror (`ROLE_DOCUMENT_TYPES`) when the catalog is unavailable, so role editing works in mock mode too; `useMenu` still gates routes with the same registry the pages use. The residual drift is limited to legacy ids still copied into some `definePageMeta`/module-config `permission` fields. The former **Page access** list was removed from the matrix.
