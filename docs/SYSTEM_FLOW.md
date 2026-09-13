# System Flow — end-to-end workflows (as implemented)

Companion reading: rules in [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md), tables in [DATABASE.md](DATABASE.md), endpoints in [API.md](API.md).

## 1. First-run & boot flow

```
docker compose up
  └─ api container: alembic upgrade head → python -m app.seed → uvicorn
       seed: sync permission catalog → Administrator role (ALL_PAGES)
             → seed admin user (SEED_ADMIN_*) → default sequences (INV…SDP)
             → default UOMs (PCS/BOX/CAN/BTL/KG/PACK) → walk-in customer
             → (dev only) sample brands/data
  └─ browser: /auth/setup/status → setupCompleted?
       false → /auth/setup  (create first admin; 409 afterwards)
       true  → /auth/login  → tokens (access 15m / refresh 7d, ver=token_version)
             → /auth/me     → profile + effectivePermissions → redirect to /
```

In-process scheduler starts with the API; expiry scan fires daily at `EXPIRY_ALERT_SCAN_HOUR` UTC (Redis NX lock prevents duplicates).

## 2. Purchase → Stock In → (supplier debt) flow

```
Stock list / Purchase Report (Create → /reports/purchases/new) ── Stock In
  lines: product + pricing UOM + qty + unit cost (+batch/expiry)
        base_qty = qty × factor_to_base ; base_cost = unit_cost ÷ factor
        header: currency (USD|KHR) + exchange_rate ; discount ≤ subtotal ; tax
        ▼ POST /stock/in   [stock.in]   (one transaction)
  allocate STI-###### (row-locked sequence)
  stock_transactions header (CONFIRMED; discount_amount/tax_amount/currency/exchange_rate)
        + items (base-UOM qty/cost snapshots)
  total = subtotal − discount + tax
  per line → apply_stock_movement(STOCK_IN)
        lock stock_balances FOR UPDATE
        recompute average_cost (weighted)
        append stock_movements (immutable)
  paid = min(paid_amount, total)
  ├─ paid < total  → supplier required → supplier_debts row (UNPAID/PARTIAL)
  │                   + Payment SDP-###### (SUPPLIER_DEBT_PAYMENT)
  ├─ paid > 0      → Payment (STOCK_IN_PAYMENT)
  audit stock_in → COMMIT
        ▼ later
  Pay supplier debt: POST /suppliers/{id}/debts/{debtId}/payments [supplier.debt.pay]
        lock debt → reject overpayment → Payment SDP-###### → paid/remaining/status → audit
```

## 3. POS / Sale → Stock Out flow

```
POS page → search (name/SKU) or barcode scan
  cart line: pricing UOM select → unit price & stock from that row
checkout [pos.access] (one transaction)
  discount? → requires pos.discount + ≤ pos.maximum_discount setting
  customer: selected or walk-in (walk-in + debt → 422)
  walk-in default: untouched "Paid now" → amount_received = amount due (paid in full)
  currency: USD|KHR + exchange_rate recorded on the sale (all amounts in it)
  allocate INV-###### → Sale + SaleItems (uom/factor/cost snapshots)
  per line → apply_stock_movement(SALE, −base_qty)   ← oversell → 409 (unless allow_negative_stock)
  includedDebtIds → lock each customer_debt → settle from amount_received
        (Payment CDP-###### + audit per debt)
  remainder → paid_for_sale ; unpaid remainder → new customer_debt (UNPAID/PARTIAL, due_date?)
  payment_status = PAID | PARTIAL | UNPAID ; change for CASH/BANK_QR
  audit sale → COMMIT
post-commit (best effort): Telegram payment text (toggle)
print: GET /pos/sales/{id}/receipt → HTML printer (A4/A5 chooser, USD/KHR
       print-currency switch with exchange rate — display-only) → browser print
```

## 4. Returns flow

```
Sale return (Sales Report / POS)  POST /pos/sales/{id}/return
  remaining = qty − returned_qty (per line) → SRT-###### → pro-rata refund
  restock? → apply_stock_movement(SALE_RETURN, +qty×factor)  |  no restock → none
  reduce sale's open customer_debt (locked) → status recompute
  sale.sale_status = RETURNED | PARTIAL_RETURN → audit

Purchase return (Purchase Report)  POST /stock/in/{id}/return  [stock.in]
  only CONFIRMED Stock In ; returnable = qty − returned_qty
  PRT-###### → PURCHASE_RETURN stock-out per line → returned_quantity += qty
  money: reduce open supplier_debt first → excess = SUPPLIER_RETURN_CREDIT payment
  refund_amount = debt_reduction + credit_amount → audit
```

## 5. Customer / supplier debt lifecycle

```
POS underpayment ──► customer_debts (UNPAID/PARTIAL)          Stock In underpayment ──► supplier_debts
  currency inherited from the sale                             currency inherited from the Stock In
        │                                                              │
        ▼ pay per debt or pay-all oldest-first (locked rows,           ▼ pay per debt / pay-all
          overpayment → 422, immutable CDP/SDP payments)                     │
        ▼                                                              purchase return reduces
  UNPAID → PARTIAL → PAID ; payments list immutable                    remaining first
  sale return reduces open customer debt before cash refund
```

## 6. Delivery Notes flow (no stock movement)

```
completed sale(s) of ONE customer
  → new note: pick invoices (deliverable-invoices) → lines qty_to_deliver ≤ outstanding
  → phone + location required → POST /delivery-notes (DN-######, DRAFT)
DRAFT ──confirm──► CONFIRMED ──out-for-delivery──► OUT_FOR_DELIVERY ──deliver──► DELIVERED
   └────────────── cancel (reason required) ──────────────┘            delivered_at stamped,
                                                                        qty_delivered = qty_to_deliver
print: GET /delivery-notes/{id}/print → HTML printer
```

## 7. Daily expiry alert flow (in-process)

```
scheduler_loop (API process, SCHEDULER_ENABLED)
  sleep until EXPIRY_ALERT_SCAN_HOUR UTC → redis SET NX lock (1 h TTL)
  → ExpiryAlertService.scan_and_send():
      enabled? (telegram.expiry_alerts_enabled)
      windows = stock.expiry_alert_1_days (90) / expiry_alert_2_days (7)
      expiring lots (stock_transaction_items.expiry_date, qty > returned)
      per lot & level (days_until ≤ window): already sent? skip
      send text to all ACTIVE users with verified telegram_chat_id
      delivered > 0 → write telegram_expiry_alert_state (once per product+batch+expiry+level)
      delivered = 0 → skip write → retried next sweep
```

## 8. Auth & password reset flow

```
login → rate limit (10/min per ip+email) → argon2 verify → status ACTIVE
      → access+refresh JWT (ver) → last_login_at → audit login
401 handling (SPA): single-flight refresh → one retry → else clear session → /auth/login
forgot password (Telegram only):
  POST /auth/forgot-password → rate limit 5/h → code (hashed, Redis, TTL 5 min, ≤5 attempts)
      → bot DM with code + deep link (FRONTEND_BASE_URL)
  POST /auth/verify-reset-code → short-lived reset_token
  POST /auth/reset-password → new argon2 hash → token_version++ (all sessions die) → audit
logout: refresh JTI → redis revocation
```

## 9. Document numbering flow

```
any document creation:
  allocate_document_number(session, TYPE)
    SELECT … FOR UPDATE on document_sequences(document_type)
    number = PREFIX-next_number (0-padded to number_length) ; next_number++
    (flush inside caller's transaction → rollback returns the number;
     missing rows self-heal; inactive sequence → 409)
TYPE catalog: INV invoice · SRT sale return · PRT purchase return · STI stock in ·
              STA adjustment · DMG damage · EXP expire · DN delivery note ·
              CUS customer · SUP supplier · CDP customer debt payment · SDP supplier debt payment
```

## 10. Audit flow

Every transactional service calls `record_audit(...)` **inside its own transaction** (never commits alone): the audit row and the business change commit or roll back together. Actions include: `initial_setup`, `login`, `login_failed`, `sale`, `sale_return`, `customer_debt_payment`, `stock_in`, `purchase_return`, `stock_adjustment`, `stock_damage`, `stock_expire`, `price_changed`, `role_created/updated`, user create/update/reset, settings update, sequence update, delivery transitions. The Audit Logs page (`audit.view`) reads them with module/action/user/date filters; rows are append-only.

## 11. Frontend navigation flow

```
/app.vue → layouts/default (AppSlidebar + AppHeader) | layouts/auth
middleware/auth.global.ts
  not logged in (tokens in sessionStorage) → /auth/login?redirect=…
  logged in + public auth page → redirect target
  definePageMeta({ permission }) → canAccessPage? : permission dialog /
      fallback to first permitted landing route
legacy-routes.global.ts: old rental URLs → mapped Stock & POS pages (no rental route reachable)
sidebar (useMenu): items filtered by permission map — see RBAC.md §5 for the key-drift caveat
```
