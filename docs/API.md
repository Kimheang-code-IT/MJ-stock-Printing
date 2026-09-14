# API Reference — `/api/v1` (as implemented)

All endpoints return `{"data": …, "meta": {"page","limit","total"}?}`; errors use the codes in [BACKEND.md](BACKEND.md) §6. Common list query parameters on every collection endpoint: `q`, `page` (≥1), `limit` (1–100, default 20), `sort`, `status`, `startDate`, `endDate`. Auth is `Authorization: Bearer <access token>` unless marked **Public**.

Permission column = FastAPI dependency actually applied in the router. `current user` = authenticated, no specific permission.

## 1. Auth (`/auth`) — see also [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) §8

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/auth/setup/status` | Public | `{setupCompleted}` — gates the Initial Setup page |
| POST `/auth/setup` | Public (once) | Create the first administrator; 409 afterwards |
| POST `/auth/login` | Public (rate-limited 10/min per ip+email) | Token pair + user payload (snake_case + camelCase aliases) |
| POST `/auth/refresh` | Public (30/min) | Rotate tokens (single rotation) |
| POST `/auth/logout` | current user | Revoke refresh JTI in Redis |
| POST `/auth/forgot-password` | Public (5/h) | Send Telegram reset code |
| POST `/auth/verify-reset-code` · `/auth/forgot-password/verify` | Public | Verify code → short-lived `reset_token` |
| POST `/auth/forgot-password/resend` | Public | Re-send code (rate-limited) |
| POST `/auth/reset-password` · `/auth/forgot-password/reset` | Public (reset token) | Set new password, bump `token_version` |
| POST `/auth/forgot-password/handoff` | Public (one-time handoff token) | Exchange Telegram deep-link handoff for a token pair |
| POST `/auth/change-password` | current user | Verify current + set new |
| PATCH `/auth/profile/avatar` | current user | Set/clear avatar |
| POST `/auth/telegram/link-code` | current user | One-time link code (10 min) for the Telegram bot |
| GET `/auth/me` | current user | Profile + effective permissions |

## 2. Categories / UOMs / Brands (Setup master data)

Each module: `GET `` (list), `POST `` (201), `GET /options` (lightweight select options), `GET/PATCH/DELETE /{id}`.

| Module | Prefix | Delete guard |
|---|---|---|
| categories | `/categories` | 409 when products reference it |
| uoms | `/uoms` | 409 when referenced (`RESTRICT`); disable instead |
| brands | `/brands` | 409 when referenced; logo upload via `/images` |

Permissions: list/get/options require `category.view` / `uom.view` / `brand.view`; create/update/delete require `category.create|update|delete` / `uom.*` / `brand.*`.

## 3. Products & sale prices (`/products`, part of stock module)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/products` | current user | List w/ barcode-first search, category & brand & status filters, `sort`, pagination, aggregated stock columns (image, barcode, name, category, brand, base UOM, current stock, cost, sale price, nearest expiry, status) |
| POST `/products` | `product.create` | Create (validates SKU/barcode unique, ACTIVE UOM required, pricing rows) |
| GET `/products/{id}` | current user | Detail incl. balance + UOM conversions |
| PATCH `/products/{id}` | `product.update` | Partial update; `selling_price` change ⇒ new sale-price version; cost change audited |
| DELETE `/products/{id}` | `product.delete` | 409 if movements or non-zero stock |
| GET `/products/sale-prices` | `stock.view` | Versioned price list (paged) |
| POST `/products/sale-prices` · `/products/{id}/sale-prices` | `product.update` | Add price version |
| PATCH `/products/sale-prices/{price_id}` | `product.update` | Edit draft price |
| POST `/products/sale-prices/{price_id}/activate` · `/products/{id}/sale-prices/{price_id}/activate` | `product.update` | Activate version (mirrors onto `selling_price`) |
| GET `/stock/products/{id}/cost-history` | `stock.view` | Cost history from Stock In lots (paged) |
| GET `/stock/products/{id}/history?type=stock_in\|stock_out\|damage\|all` | `stock.view` | Movement history behind the Stock list dialogs |

## 4. Stock operations (`/stock`)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/stock/operations` | `stock.view` | Purchase/operation documents (type, supplier, date range, status, q) — read model for the purchase list & dialogs |
| POST `/stock/operations` | current user | Quick single-product operation `type=stock_in\|adjustment\|damage\|expiry` from the Stock list |
| POST `/stock/in` | `stock.in` | Stock In transaction (lines in pricing UOM, supplier, header discount/tax, document currency `USD`\|`KHR` + exchange rate, paid amount, supplier debt, payment) |
| PATCH `/stock/in/{id}` | `stock.in` | **Edit a confirmed Stock In** (guarded: only `CONFIRMED` docs with no purchase returns). Reverses the original receipt (batch + compensating `PURCHASE_RETURN` movements), re-applies the new lines, recalculates header totals and the outstanding supplier debt (immutable payments kept). Body: `items[]`, `discount_amount`, `tax_amount`, `currency`, `exchange_rate`, `note?`, `reference_no?`, `transaction_date?` |
| POST `/stock/in/{id}/return` | `stock.in` | Purchase return (PRT) against a confirmed Stock In (endpoint kept; not linked from the UI) |
| POST `/stock/adjust` | `stock.adjust` | Counted adjustment (system vs actual) |
| POST `/stock/damage` | `stock.damage` | Damage write-off |
| POST `/stock/expire` | `stock.expire` | Expiry write-off (product must track expiry) |
| GET `/stock/movements` | `stock.view` | Immutable movement ledger (q, product, movement type, date range, pagination, `sort`) — read model for the Stock Movements page. Rows carry product, barcode, type, UOM symbol (line snapshot or base UOM), qty in/out, balance before/after (derived from the ledger), document/source reference, user. No write endpoints exist |

## 5. POS (`/pos`)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/pos/products/search` | `pos.access` | Name/SKU search, category filter, ≤ 50, ACTIVE |
| GET `/pos/products/barcode/{barcode}` | `pos.access` | Barcode scan lookup |
| GET `/pos/sales` | `pos.access` | Sales list (q=invoice no, customer, date range) |
| POST `/pos/sales` · **`POST /pos/sales/complete`** | `pos.access` | Complete sale atomically (the SPA uses `/complete`) |
| PATCH `/pos/sales/{id}` | `pos.access` | **Edit a completed sale** (guarded: only `COMPLETED` with no returns). Reverses the original stock (compensating `SALE_RETURN` movements restored to the original batches) and re-applies the new lines/prices/discounts; customer and immutable payments stay, the customer debt is recalculated. Body: `items[]`, `discount`, `delivery_price`, `currency`, `exchange_rate`, `note?`, `sale_date?` |
| GET `/pos/sales/{id}` | `pos.access` | Sale detail + items; loaded into POS **edit mode** (`/pos?editSaleId=<id>`) and legacy **return mode** (`/pos?returnSaleId=<id>`) |
| POST `/pos/sales/{id}/return` | `pos.access` | Sale return (SRT), optional restock (endpoint kept; not linked from the UI) |
| POST `/pos/sales/{id}/delivery` | `delivery.create` | Create delivery note from the sale |
| GET `/pos/sales/{id}/receipt` | `pos.access` | JSON print payload for the HTML printer (no PDF endpoint exists — invoices print from the browser only). Carries invoice no, date, customer + phone/address, cashier, payment method, document `currency` + `exchange_rate` (preserved from sale time), items (UOM/qty/unit price/discount/line total), subtotal/discount/delivery fee/grand total/paid/debt/change, shop info, paper size, exchange-rate display flag, footer |

Sale payload essentials: `items[{productId, uomId?, factorToBase?, quantity, unitPrice?, discountPercent?|discountAmount?}]`, `discount` (header), `deliveryPrice`, `customerId?` (walk-in when omitted), `currency` (`USD`\|`KHR`) + `exchangeRate` (KHR per 1 USD; every amount on the sale is in this currency), `amountReceived`, `paymentMethod` (`CASH`/`BANK_QR`/`CUSTOMER_DEBT`), `depositMethod?`, `includedDebtIds[]`, `dueDate?`, `note?`. Walk-in default: the frontend sends `amountReceived = amount due` when **Paid now** is left untouched, so `POST /pos/sales` with no `customerId` completes a fully paid walk-in cash sale; underpayment (`amountReceived < total`) on a walk-in is rejected 422.

## 6. Customers (`/customers`)

| Method & path | Permission | Purpose |
|---|---|---|
| GET/POST `/customers`, GET/PATCH/DELETE `/customers/{id}` | list/get: current user; mutations: `customer.create/update/delete` | CRUD; delete 409 when referenced |
| GET `/customers/options` | `customer.view` | Lightweight active-customer select options |
| GET `/customers/{id}/debts` | current user | Debt list w/ sale info |
| GET `/customers/{id}/purchase-history` | current user | Paginated sales |
| GET `/customers/{id}/payments` | current user | All payments |
| POST `/customers/{id}/payments` | `customer.debt.pay` | Pay open debts oldest-first (one transaction) |
| GET/POST `/customers/{id}/debts/{debtId}/payments` | list: current user · create: `customer.debt.pay` | Per-debt payments; overpayment → 422 |

## 7. Suppliers (`/suppliers`) — mirrors customers

CRUD (`supplier.*`), `GET /options` (lightweight active-supplier options), `GET /{id}/debts`, `GET /{id}/payments`, `POST /{id}/payments` (`supplier.debt.pay`, oldest-first), `GET/POST /{id}/debts/{debtId}/payments`, `GET /{id}/history` (Stock In history).

## 8. Delivery Notes (`/delivery`, nested aliases)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/delivery` | `delivery.view` | List (q, status, customer, date range) |
| POST `/delivery` | `delivery.create` | Create (from one or more sales of one customer) |
| GET `/delivery/deliverable-invoices` | `delivery.view` | Invoices with undelivered quantities |
| GET/PATCH `/delivery/{id}` | view / `delivery.update` | Detail / edit DRAFT |
| POST `…/{id}/confirm` `…/out-for-delivery` `…/deliver` | `delivery.confirm` / `delivery.deliver` | Status machine (Confirm requires `delivery.confirm`; Out/Deliver require `delivery.deliver`) |
| POST `…/{id}/cancel` | `delivery.cancel` | Requires reason |
| POST `…/{id}/status` | `delivery.update` | Legacy single-step transition endpoint |
| GET `…/{id}/print` | `delivery.view` | Print payload for HTML print |
| GET `/sales/{saleId}/deliverable-items` | `delivery.view` | Undelivered quantities per sale item |
| POST `/pos/sales/{saleId}/delivery` | `delivery.create` | Alias creation route from POS |
| GET `/customers/{customerId}/delivery` | `delivery.view` | Customer's notes |

## 9. Dashboard (`/dashboard`)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/dashboard/summary` | `dashboard.view` | KPIs, chart series, alerts, recent activity, top products (`period`, `startDate`, `endDate`) |

## 10. Reports (`/reports`)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/reports/sales` + `/sales/export` | `report.sales` | Sales report (+CSV) |
| GET `/reports/purchase` and `/reports/purchases` (+ `/export` each) | `report.purchase` | Purchase report (plural = SPA alias) |
| GET `/reports/sale-returns` | `report.sales` | Customer-return history (immutable `sale_returns` documents). No dedicated page; history stays server-side. The Sales Report row action is now **Edit** (not Return) |
| GET `/reports/purchase-returns` | `report.purchase` | Supplier-return history (immutable `purchase_returns` documents). No dedicated page; history stays server-side. The Purchase Report row action is now **Edit** (not Return) |
| GET `/reports/customer-debts` (+ export) | `report.customer_debt` | Customer debt report; optional `currency=USD\|KHR` filter (USD and KHR rows are never mixed) |
| GET `/reports/supplier-debts` (+ export) | `report.supplier_debt` | Supplier debt report; optional `currency=USD\|KHR` filter |
| GET `/reports/finance` | `report.finance` | Finance summary (formulas in [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) §14) |
| GET `/reports/finance/summary` · `/finance/entries` | `report.finance` | Summary cards / income & expense ledger |
| POST `/reports/finance/expenses` | `report.finance` **and** `expense.create` | Add Expense modal |

## 11. Administration (`/admin`)

| Method & path | Permission | Purpose |
|---|---|---|
| GET/POST `/admin/users`, PATCH `/admin/users/{id}` | `user.manage` | User management; last-active-admin guard |
| POST `/admin/users/{id}/reset-password` | `user.manage` | Admin reset (bumps token_version) |
| GET `/admin/roles`, POST `/admin/roles`, PATCH `/admin/roles/{id}` | `role.manage` | Role matrix; unknown permission codes → 422 |
| GET `/admin/roles/options` | `role.manage` | Lightweight active-role select options |
| GET `/admin/permissions` | `role.manage` (catalog read) | Permission catalog for the matrix |
| GET `/admin/document-sequences`, PATCH `/admin/document-sequences/{id}` | `sequence.manage` | Prefix / next number / length / status |
| GET `/admin/audit-logs` | `audit.view` | Filtered audit trail (module, action, user, dates) |
| GET/PATCH `/admin/settings` | `settings.manage` | Grouped settings; secrets masked |
| POST `/admin/settings/telegram-test` | `settings.manage` | Send a Telegram test notification; soft result `{enabled, sent, recipients}` |

## 11a. Settings surface (`/settings`)

SPA-facing projection of the grouped settings catalogue. Reads require an authenticated user; writes require `settings.manage`.

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/settings/app-config` | current user | Full App Config document (general/localization/email/telegram/stock/notifications/security/system); bot token masked |
| PATCH `/settings/app-config` | `settings.manage` | Partial App Config write, mapped onto known groups only |
| GET/PATCH `/settings/app-info` | view: current user · update: `settings.manage` | Shop identity/branding projection (`shop` group) |
| POST `/settings/app-info/reset` | `settings.manage` | Restore the `shop` group defaults |
| POST `/settings/app-config/email/test-connection` · `/email/send-test` | `settings.manage` | Returns `status: disabled` (no email subsystem) |
| POST `/settings/app-config/telegram/test-connection` · `/telegram/send-test` | `settings.manage` | Telegram connectivity/delivery test → `{status, message}` |
| POST `/settings/reset-data` | `settings.manage` | Refused with `FEATURE_DISABLED`; resets go through DB maintenance |

## 12. Images & health

| Method & path | Permission | Purpose |
|---|---|---|
| POST `/images/upload` | current user | Multipart image upload → `{objectKey, url}` (5 MB cap) |
| GET `/images/{object_key:path}` | Public (static media) | Serve stored image (traversal-guarded) |
| GET `/health` · `/api/v1/health` | Public | Liveness + DB/Redis status |

## 12a. Search (`/search`)

| Method & path | Permission | Purpose |
|---|---|---|
| GET `/search?q=&limit=` | current user | Global command-palette search. Returns `{hits, total}`; each type (product/customer/supplier/sale) is included only when the caller holds `stock.view` / `customer.view` / `supplier.view` / `report.sales`. Blank `q` → empty result. |

## 13. Frontend endpoint notes

- Base URL resolves from `runtimeConfig` (`NUXT_PUBLIC_API_BASE`), same-origin in the nginx compose setup.
- 401 handling: single-flight refresh (`createAuthRefresher`) then exactly one retry; on final failure the session is cleared. 403 triggers a re-fetch of `/auth/me` and the permission-denied dialog.
