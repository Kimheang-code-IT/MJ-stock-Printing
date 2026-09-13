# Business Logic — rules as implemented

Every rule below is enforced in backend services (`backend/app/modules/*/service.py`); the frontend mirrors some of them purely for UX. Architecture overview: [PROJECT.md](PROJECT.md). Tables: [DATABASE.md](DATABASE.md). Endpoints: [API.md](API.md).

## 1. Canonical stock mutation (`stock/service.py::apply_stock_movement`)

The single entry point that changes `stock_balances`. Contract:

1. Validates `movement_type` ∈ {STOCK_IN, SALE, SALE_RETURN, PURCHASE_RETURN, ADJUSTMENT_IN, ADJUSTMENT_OUT, DAMAGE, EXPIRE} and non-zero delta (quantized to 4 dp).
2. Locks the balance row `SELECT … FOR UPDATE` (with `populate_existing` to defeat stale identity-map reads); creates a zero balance if absent.
3. If delta < 0 and the result would go negative: **409 Conflict "Insufficient stock"** unless the caller passes `allow_negative` (from setting `pos.allow_negative_stock`).
4. On `STOCK_IN` with positive delta, recomputes the weighted **average cost**: `(qty·avg + inQty·cost) / (qty+inQty)`, 2 dp half-up.
5. Appends an immutable `stock_movements` row (type, delta, unit cost, polymorphic reference, document no, batch, expiry, UOM symbol, note, actor) and updates the balance — all in the caller's transaction.

Direct writes to `stock_balances` from CRUD endpoints do not exist; `ProductService` never touches quantities.

## 2. Purchase → Stock In (`POST /stock/in`, perm `stock.in`)

1. Duplicate-product check per request; every product must exist; supplier (optional) must exist.
2. Per line: `uom_id` must be the product's base UOM (factor forced to 1) or a row of `products.uom_conversions` with a matching `factor_to_base` (> 0); `base_quantity = quantity × factor`; `base_unit_cost = unit_cost ÷ factor`; `line_total = quantity × unit_cost` (2 dp).
3. Header adjustments: `discount_amount` cannot exceed the line subtotal (422); `total = subtotal − discount_amount + tax_amount`. The document records `currency` (`USD`\|`KHR`) + `exchange_rate` (KHR per 1 USD) — every amount on it is in that currency.
4. Document number `STI-######` allocated (row-locked sequence); `stock_transactions` header created `CONFIRMED` with actor as creator+confirmer.
5. Each line: `STOCK_IN` movement via the canonical mutation (updates average cost, records batch/expiry).
6. **Payment**: `paid = min(paid_amount, total)`; negative rejected. If `paid < total` a supplier is **required** — `supplier_debts` row is created in the document currency (`original=total`, `paid=paid`, `remaining=total−paid`, status `UNPAID`/`PARTIAL`). If `paid > 0` an immutable `Payment` row is written (`STOCK_IN_PAYMENT`, or `SUPPLIER_DEBT_PAYMENT` when partial; method defaults CASH).
7. Audit `stock_in` with totals; commit. Return payload includes debt id when created.

## 3. POS sale → Stock Out (`POST /pos/sales/complete`, perm `pos.access`)

One atomic transaction (rollback discards everything):

1. **Discount authorization** — any line or header discount requires `pos.discount`; per-line and header discounts are additionally capped by setting `pos.maximum_discount` (0 = unlimited) and cannot reach/exceed the line/sale amount.
2. Customer: payload id or the seeded **walk-in** customer; walk-in cannot take debt. The frontend leaves `customerId` empty for walk-in sales and (by default) sends `amount_received = amount due` — an untouched **Paid now** input pays the full balance, so a walk-in cash sale submits without typing the tender.
3. Cart validation: no duplicate products; products must be ACTIVE; per-line UOM must be the base or a pricing row (price falls back to that row's `sale_price`); `base_quantity = quantity × factor_to_base` > 0.
4. Invoice no `INV-######` allocated; `Sale` header + `SaleItem` rows (UOM/code/symbol/factor/name/SKU/barcode snapshots, `unit_cost` = balance average at sale time, per-line discount, line_total). The sale records `currency` (`USD`\|`KHR`) + `exchange_rate` (KHR per 1 USD) — lines, discounts, delivery, paid and debt amounts are all in that currency, never mixed.
5. Each line: `SALE` movement (negative base qty) via the canonical mutation — oversell blocked by the same insufficient-stock rule.
6. Header discount applied after line discounts; `grand_total = subtotal − discount_total + delivery_price` (delivery fee does **not** cause a second stock-out).
7. **Included debt settlement**: each `includedDebtIds` row is locked, verified to belong to the sale's customer and still open, then paid oldest-first from `amount_received` — each application writes a `CUSTOMER_DEBT_PAYMENT` payment + audit.
8. Remaining tender pays the sale (`SALE_PAYMENT`); whatever is left unpaid becomes `debt_amount` → a `customer_debts` row (`UNPAID` if nothing paid, `PARTIAL` otherwise) with optional `due_date`. `payment_status` ∈ PAID/PARTIAL/UNPAID.
9. Change returned for CASH/BANK_QR: `amount_received − settled − grand_total` (floored at 0).
10. Audit `sale`; commit. **Post-commit best effort** (never rolls back): Telegram sale notification (CASH/BANK_QR, toggle `telegram.sale_enabled`, canonical service `app.shared.telegram.service`).

## 4. Sale return (`POST /pos/sales/{id}/return`)

- Allowed while `sale_status ∈ {COMPLETED, PARTIAL_RETURN}`; per-line remaining = `quantity − returned_quantity` (422 when exceeded).
- `SRT-######` header; refund = `line_total × qty / lineQty` (pro-rata); `restock` lines create a `SALE_RETURN` movement (+`qty × factor_to_base`, cost = sold unit cost) and restore the **original sold batch allocations** (newest allocation first — never an arbitrary batch); no restock = no stock change.
- The sale's open `customer_debts` row (locked) is reduced by the refund (status recomputed) — money never goes negative.
- `sale_status` → `RETURNED` when all lines fully returned, else `PARTIAL_RETURN`. Audit `sale_return`. The POS **return mode** (`/pos?returnSaleId=<id>`) still supports this but is no longer linked from the UI (report/customer-history rows now use **Edit**); it never creates a new sale.

## 5. Purchase return (`POST /stock/in/{id}/return`, perm `stock.in`)

- Only confirmed `STOCK_IN` documents; the header is locked. Per line, returnable = `quantity − returned_quantity` (422 when exceeded).
- `PRT-######` header + items (base-UOM qty, original unit cost, line refund); `PURCHASE_RETURN` stock-out per line deducting the **original batch lot** (batch identity = product + batch_no; unbatched lines drain FEFO); `stock_transaction_items.returned_quantity` accumulates.
- **Money**: reduces the purchase's open `supplier_debts` (locked) up to `remaining_amount`; any excess becomes a `SUPPLIER_RETURN_CREDIT` payment (method CREDIT) recorded against the document. `refund_amount = debt_reduction + credit_amount`. Audit `purchase_return`. The Purchase **return mode** (`/reports/purchases/new?returnPurchaseId=<id>`) still supports this but is no longer linked from the UI (report/supplier-history rows now use **Edit**); it never creates a new purchase.

## 6. Stock adjustment / damage / expiry (`POST /stock/adjust|damage|expire`)

- **Adjustment** (perm `stock.adjust`): per line `system_quantity` (defaults to the locked balance), `actual_quantity`, required reason; `difference = actual − system` → `ADJUSTMENT_IN`/`ADJUSTMENT_OUT` movement at average cost; zero-difference lines are recorded without a movement. Document `STA-######`.
- **Damage** (`stock.damage`): positive quantities out at supplied or average cost → `DAMAGE` movement; document `DMG-######`.
- **Expire** (`stock.expire`): same but the product must have `expiry_tracking = true`; may carry `batch_no`/`expiry_date`; document `EXP-######`. Loss values feed the Finance report.

## 7. Debts (customer & supplier)

- Created only as side effects: POS underpayment (customer), Stock In underpayment (supplier). One open debt per sale / per stock-in document. A debt **inherits the currency and exchange rate of its source document**, so payments and history stay in the debt's own currency.
- **Payment endpoints** (perm `customer.debt.pay` / `supplier.debt.pay`): lock the debt row; reject already-settled debts (409) and **overpayment (422)**; insert immutable `Payment` (`CUSTOMER_DEBT_PAYMENT` / `SUPPLIER_DEBT_PAYMENT`, `CDP-`/`SDP-######`); update `paid/remaining/status` in the same transaction; audit; post-commit Telegram notify (customer side).
- **Customer-level pay-all** (`POST /customers/{id}/payments`): settles open debts **oldest-first** in one transaction; total must not exceed the sum of remaining amounts.
- Sale returns and purchase returns reduce the related open debt before issuing credits (§4, §5).

## 8. Auth & account lifecycle

- **Initial setup once**: `POST /auth/setup` refused (409) if any user exists; creates the Administrator system role (`ALL_PAGES`) and audits `initial_setup`.
- **Login**: rate limited (10/min per ip+email; Redis, fail-open if Redis is down), Argon2 verify, disabled accounts rejected, failed attempts audited (`login_failed`), access 15 min + refresh 7 d JWTs carrying `token_version`.
- **Logout/refresh**: refresh JTI revoked via Redis; rotation on refresh.
- **Password reset (Telegram only)**: code generation → hashed storage in Redis with 5-min TTL, max 5 attempts, 5 requests/hour; verify returns a short-lived reset token; reset bumps `token_version` (invalidates all sessions). Delivery via the server-side bot token only.
- Admin password reset (`/admin/users/{id}/reset-password`) and change-password both re-hash and bump `token_version`; the **last active administrator** cannot be disabled or demoted.

## 9. Telegram integrations (canonical service: `app/shared/telegram/service.py`)

All business notifications flow through one canonical service. Every send is:

- **Settings-gated**: `telegram.enabled` master switch + per-type toggles (`sale_enabled`, `purchase_enabled`, `daily_summary_enabled`, `expiry_alerts_enabled`) — changed in Administration → Settings, effective immediately.
- **Post-commit only**: called after the business transaction commits; a delivery failure is logged and swallowed — it can never roll back a sale, Stock In, payment, or delivery.
- **Text-only**: no invoice/receipt files or PDFs are ever sent.
- **Recipients**: every ACTIVE user with a verified `telegram_chat_id`; the bot token comes from the `TELEGRAM_BOT_TOKEN` environment variable (never the DB).

| Feature | Trigger | Safeguards |
|---|---|---|
| Password-reset codes | user request | hashed code, TTL, attempt caps, rate limit, secrets server-side |
| Account linking | `POST /auth/telegram/link-code` | one-time code, 10-min TTL |
| Sale notification | committed CASH/BANK_QR sale | `telegram.sale_enabled`; text summary incl. currency (never mixed USD/KHR) |
| Purchase notification | committed Stock In | `telegram.purchase_enabled`; supplier, totals, paid/debt |
| Debt-payment text | committed customer debt payment | gated by `telegram.sale_enabled` (payments are the sale's payment stream) |
| Daily summary | in-process scheduler after the expiry-scan slot | `telegram.daily_summary_enabled` + `daily_summary_time`; per-currency USD/KHR totals NEVER summed together; includes sale count/totals, purchase count/totals, outstanding customer + supplier debts, delivered/pending delivery counts, out-of-stock count |
| Expiry alerts | daily in-process scan at `EXPIRY_ALERT_SCAN_HOUR` UTC | levels 1/2 from settings `stock.expiry_alert_1_days` (90) / `_2_days` (7); one alert per (product, batch, expiry, level) via `telegram_expiry_alert_state`; delivered>0 required before state is written, else retried next day |
| Test notification | `POST /admin/settings/telegram-test` (perm `settings.manage`) | soft result `{enabled, sent, recipients}`; never raises |
| Stock inquiry bot (`telegram_bot.py`) | optional `telegram-bot` compose profile | **view-only**; never sends invoice/payment documents |

## 10. Document numbering (`shared/documents/service.py`)

- `document_sequences` rows: prefix + `next_number` + `number_length` (6) + status. `allocate_document_number` locks the row, formats `PREFIX-000001`, increments, flushes — inside the caller's transaction, so concurrent allocations serialize and a rollback returns the number to the pool (gaps appear only on rollback; collisions impossible).
- Catalog: `INV`, `SRT`, `PRT`, `STI`, `STA`, `DMG`, `EXP`, `DN`, `CUS`, `SUP`, `CDP`, `SDP`. Missing rows self-heal (conflict-safe insert) for databases predating a sequence type. Inactive sequence → 409.

## 11. Delivery state machine

```
DRAFT ──confirm──► CONFIRMED ──out-for-delivery──► OUT_FOR_DELIVERY ──deliver──► DELIVERED
  │                     │                                 │
  └────────cancel (reason required)───────────────────────┘        (DELIVERED is final)
```

- Phone + location must be non-empty before Confirm/Out/Deliver (they are the only destination fields; a note without them falls back to the customer snapshot at creation).
- Confirm/out/deliver/cancel each have their own permission (`delivery.confirm` / `delivery.deliver` / `delivery.cancel`).
- `DELIVERED` stamps `delivered_at` and sets `qty_delivered = qty_to_deliver` on all items. Quantities never exceed the sale's outstanding (ordered − already on other notes − delivered). **No stock movement is ever created.**

## 12. Product master rules

- SKU unique; barcode unique when present; base UOM required and ACTIVE; brand/category optional but must exist (brand must be ACTIVE).
- `selling_price` edits create + activate a new `product_sale_prices` version atomically (POS reads the active version; the stock list reads `selling_price` — they cannot diverge). Cost-price edits are audited (`price_changed`).
- Pricing rows (`uom_conversions`): validated UOM ids, positive factors, one default-sale row; base row synthesized for legacy products at read time.
- Delete: 409 when any movement exists or balance ≠ 0.

## 13. Audit coverage

Actions recorded inside the same transaction as the change: `initial_setup`, `login`, `login_failed`, `sale`, `sale_return`, `customer_debt_payment`, `stock_in`, `purchase_return`, `stock_adjustment`, `stock_damage`, `stock_expire`, `price_changed`, role create/update, user create/update/reset, settings update, sequence update, delivery transitions, and generic module CRUD audited by the shared services. Rows are append-only; IP/UA captured from the request.

## 14. Finance report formulas (`/reports/finance`, perm `report.finance`)

Income is **derived read-only from POS data** (no duplicate income tables); the only user-managed rows are `expenses` (created via the Add Expense modal — no dedicated page, no `/expenses` route).

| Metric | Formula (as implemented) |
|---|---|
| Total sales | Σ `sales.grand_total` in period − Σ `sale_returns.refund_amount` in period |
| COGS | Σ `sale_items.unit_cost × quantity` − Σ (restocked sale-return qty × sold unit cost) |
| **Gross profit** | Total sales − COGS |
| Operating expenses | Σ `expenses.amount` in period (Stock In purchase cost is deliberately **not** an expense line) |
| Stock damage loss | Σ −`quantity_delta × unit_cost` where movement_type = DAMAGE |
| Stock expiry loss | same, movement_type = EXPIRE |
| **Net result** | Gross profit − damage loss − expiry loss − operating expenses |
| Total purchase cost | Σ Stock In `line_total` in period |
| Total customer debt | Σ all `customer_debts.remaining_amount` (all time) |
| Total supplier debt | Σ all `supplier_debts.remaining_amount` (all time) |

- **`GET /reports/finance/entries`**: the income/expense ledger table (sales income rows, refund rows, expense rows) with filters — an income/expense **table** per the approved UI.
- **`POST /reports/finance/expenses`** (perm `report.finance` **and** `expense.create`): `expense_date` (≤ today), category, description, optional reference, amount > 0, currency + exchange rate, optional payment method. Audited; appears immediately in the ledger and the next summary.
- **Currency normalization**: every money document records `currency` + `exchange_rate` (KHR per 1 USD). Finance aggregates never mix raw amounts — a `_usd(expression, currency, rate)` helper passes USD rows through and divides KHR rows by their stored rate (applies to sales, refunds, COGS, purchases, debts, expenses). Damage/expiry losses come from the movement cost ledger (per-mutation base-unit cost, no document currency) and stay as recorded.

## 15. Report grains & exports (`/reports/*`)

All report endpoints accept the common list params (`q`, `page`, `limit`, `startDate`, `endDate`) plus report-specific filters and return the standard envelope; each has a CSV export twin (`…/export`) streamed server-side (no stored export files).

- **Sales** (`report.sales`): one row per **sale item** joined to its sale (invoice no, date, customer, cashier, product, qty + UOM snapshot, unit price, discount, line total, payment method, payment status); totals in `meta`; UI adds the per-invoice **Edit** action (POS edit mode → `PATCH /pos/sales/{id}`) and invoice print.
- **Purchase** (`report.purchase`): `stock_transactions` type `STOCK_IN` CONFIRMED with items aggregated (STI-…, supplier, reference, item summary, total, paid vs debt); UI adds the full-page Create flow and the per-document **Edit** action (Purchase edit mode → `PATCH /stock/in/{id}`).
- **Customer/Supplier Debt** (`report.customer_debt` / `report.supplier_debt`): debt rows joined to sales/stock-in documents (original, paid, remaining, due date, status; overdue highlight); optional `currency=USD|KHR` filter; UI adds the Pay dialog (single + multi-select oldest-first) and export.
- **Customer/Supplier Returns** (`report.sales` / `report.purchase`): server-side history of immutable `sale_returns` (SRT-…, restocked qty, refund, reason) and `purchase_returns` (PRT-…, refund split debt-reduction + credit, reason) documents. No dedicated page; the report row actions are now **Edit**. The raise-return endpoints still exist but are no longer linked from the UI; `returned_quantity` on source lines stays the returnable-quantity source of truth.
- **Dashboard** (`dashboard.view`, cached ~60 s in Redis): KPIs (today/this-month sales, pending delivery notes, operating expenses today, debt totals, damage/expiry loss, refunds, gross profit), daily sales chart series, low-stock (`quantity ≤ minimum_stock`) and expiring (90/7-day windows) alert counts, recent sales/activity, top products.

## 16. Editing a completed sale / purchase (reverse + reapply)

Sales and purchases are otherwise immutable: `apply_stock_movement` is append-only and `Payment` rows are never edited. Editing reuses that discipline by **appending compensating movements** and re-applying the document, never mutating the ledger.

- **Sale** — `PATCH /pos/sales/{id}` (perm `pos.access`), UI at `/pos?editSaleId=<id>`.
  - **Guards**: the sale must be `COMPLETED` and have **no returns** (`returned_quantity == 0` on every line); otherwise 409. Discount rules and max-discount settings are re-validated exactly like `complete_sale`.
  - **Reverse**: for each existing line, restore its `SaleItemBatch` allocations (newest-first, same as a return) and append a compensating `SALE_RETURN` movement (`+base_qty`); then delete the old `SaleItem`s.
  - **Reapply**: build the new lines through the same UOM/batch/FEFO/discount path as `complete_sale` (new `SaleItem` + `SaleItemBatch` rows + `SALE` movements), and rewrite header `subtotal/discount/delivery/grand_total/currency/exchange_rate/note/sale_date`.
  - **Debt**: the sale's `customer_debts` row is locked and recalculated from the new grand total using the **already-paid** amount (`paid_for_sale = min(existing_paid, grand_total)`); a walk-in with a resulting balance is rejected. Recorded payments are untouched, so payment-method changes are not part of the edit.
  - Audited as `sale_update`.
- **Purchase / Stock In** — `PATCH /stock/in/{id}` (perm `stock.in`), UI at `/reports/purchases/new?editPurchaseId=<id>`.
  - **Guards**: `transaction_type == STOCK_IN`, `status == CONFIRMED`, and **no purchase returns** (`returned_quantity == 0` on every line); otherwise 409.
  - **Reverse**: for each existing line, deduct its original batch lot (or FEFO for unbatched lines) and append a compensating `PURCHASE_RETURN` movement (`−base_qty`); then delete the old items.
  - **Reapply**: create the new `StockTransactionItem`s, `batch_in` each lot and append `STOCK_IN` movements with the same batch/expiry/UOM validation as `stock_in`; rewrite header `discount/tax/currency/exchange_rate/note/reference/date`.
  - **Debt**: the linked `supplier_debts` row is locked and recalculated from the new total with the already-paid amount; full payment is required when no supplier is set. Immutable payments are kept.
  - Audited as `stock_in_update`.
