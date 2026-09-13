# Testing (as implemented)

## 1. Backend — `python -m pytest backend/tests`

Async pytest + httpx against a **real PostgreSQL** (`stock_pos_test` on localhost:55432) and Redis (localhost:56379/5) — the host ports published by `docker-compose.yml`. `tests/conftest.py` sets env overrides (high rate limits, scheduler off, temp media dir), creates the test database, runs migrations, and provides app-client + auth fixtures (login helper, permission-granting helper). `tests/utils.py` seeds a fixed "Each" UOM and factory helpers.

### Suite map (spec §9.4 coverage)

| Area | Files | Covers |
|---|---|---|
| Health | `api/test_health.py` | liveness, DB/Redis |
| Auth | `modules/auth/test_setup.py`, `test_login.py`, `test_reset.py`, `test_permissions.py`, `test_profile_frontend.py` | one-time setup, login lockout/rate, refresh rotation, logout revocation, Telegram reset codes (hashed, TTL, attempt caps), token_version bumps, `/auth/me` payload aliases, permission matrix behavior |
| Master data | `modules/categories/…`, `uoms/…`, `brands/…`, `suppliers/test_suppliers.py`, `customers/test_customers.py` | CRUD contracts, delete guards, permission enforcement, code generation |
| Stock | `modules/stock/test_products.py`, `test_operations.py`, `test_stock_in_uom.py`, `test_sale_prices.py`, `test_purchase_return.py`, `test_history_and_operations.py`, `test_stock_aggregates.py`, `test_live_contract.py`, `test_product_images.py` | product validation, UOM factor conversion (base-UOM mutation), average costing, insufficient-stock rejection, adjustments/damage/expiry, sale-price versioning + active mirror, purchase return math (debt reduction vs credit), stock-in header discount/tax totals + document currency (incl. KHR purchase debt), history endpoints, movement→invoice click-through |
| POS | `modules/pos/test_sale.py`, `test_sale_extras.py`, `test_debts.py`, `test_party_payments.py`, `test_returns.py`, `test_return_pack_uom.py`, `test_concurrency.py`, `test_telegram_notify.py` | atomic sale completion, discounts (permission + maximum-discount cap), walk-in debt ban, included-debt settlement, overpayment rejection, pro-rata returns + restock, pack-UOM returns, KHR sales recording document currency + debt currency, **concurrent sale / sequence races** (no oversell, no duplicate invoice), Telegram notify gating |
| Delivery | `modules/delivery_notes/test_delivery_notes.py`, `test_status_route.py`, `test_pos_alias.py` | deliverable math, status machine, phone/location requirement, cancel reason, no stock impact, POS alias routes |
| Reports/Finance | `modules/reports/test_reports.py`, `test_finance.py`, `test_finance_contracts.py`, `test_debug_fin.py` | sales/purchase/debt report filters & totals; return-history reports (sale/purchase returns); finance formulas (sales − refunds, COGS − restock, damage/expiry loss, expenses, net result); KHR expense + summary currency normalization; expense creation permission pair |
| Administration | `modules/administration/test_admin.py` | users (last-active-admin guard), roles (unknown permission → 422, Administrator must keep ALL_PAGES), sequences, settings masking, audit filters |
| Telegram | `modules/telegram/test_expiry_alerts.py`, `shared/telegram/test_inquiry.py` | alert windows (90/7), once-per-lot state, delivery-failure retry, view-only inquiry |
| Shared | `shared/test_documents.py`, `services/test_image_storage_service.py` | concurrent sequence allocation (collision-free), image caps/traversal |

Run locally (docker stack must be up for the published ports):
```bash
python -m pytest backend/tests                      # all
python -m pytest backend/tests/modules/pos -q       # focused while iterating
```

## 2. Frontend — `pnpm --dir frontend test` (Vitest)

Pure unit/adapter tests (no browser):

| File | Covers |
|---|---|
| `api-base-url.spec.ts`, `api-errors.spec.ts`, `auth-refresher.spec.ts`, `auth-tokens.spec.ts` | base-URL resolution, error normalization, single-flight 401 refresh, sessionStorage token lifecycle |
| `rbac.spec.ts`, `security-boundaries.spec.ts` | permission matrix normalization/flattening, action dependencies, safe URL/file handling, fail-closed checks |
| `pos-checkout.spec.ts`, `pos-uom.spec.ts`, `pos-chrome.spec.ts` | cart/checkout math, UOM price switching, POS chrome behavior |
| `delivery-notes.spec.ts`, `document-tabs.spec.ts`, `audit-logs.spec.ts` | delivery status helpers, document tabs, audit label/format helpers |
| `print-documents.spec.ts` | invoice/delivery HTML printer payload structure, print-currency conversion (KHR rounding, exchange-rate meta, USD record printed as USD), A5 signature/filler layout |
| `mock-repositories.spec.ts`, `repositories.spec.ts`, `search-adapter.spec.ts` | repository contract parity (mock vs http), complete-purchase (Stock In) command (single document, discount/tax/currency fields), search index |
| `filter-values.spec.ts`, `form-layout.spec.ts`, `header-actions.spec.ts`, `file-preview.spec.ts`, `telegram-settings.spec.ts` | filters, form layout, header actions, file previews, settings schema |
| `format-service.spec.ts`, `localization-config.spec.ts`, `list-table.spec.ts`, `list-columns`, `table theme` | money/date formatting, en/km locale config, table rendering utilities |

Additional commands: `pnpm --dir frontend typecheck`, `lint`, `build`.

## 3. CI gates (`.github/workflows/ci.yml`)

1. `docker compose -f docker-compose.yml config --quiet` (+ prod overlay).
2. Frontend: install → prepare → **test** → **typecheck**.
3. Backend: **pytest** with Postgres/Redis service containers.

`publish-images.yml` only publishes images; it does not re-run tests.

## 4. Gaps worth closing (observations, no code changed)

- Backend coverage is strong on transactional integrity, but there is **no dedicated test** for the `POST /stock/operations` quick-operation path under concurrency.
- The frontend permission matrix drift ([RBAC.md](RBAC.md) §5) is untested end-to-end: `rbac.spec.ts` validates the matrix utilities, not that saved role keys match the backend catalog.
- No e2e/browser tests; POS barcode workflow and print flows are covered only by unit tests of their utility modules.
- No coverage reporting is configured in CI (pass/fail only).
