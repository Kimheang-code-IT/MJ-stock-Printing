# Database — PostgreSQL schema (as implemented)

Authoritative store for all stock, sales, payments, debts, sequences, settings and audit data. SQLAlchemy 2 models define the schema; **every change goes through an Alembic migration** (`backend/alembic/versions/0001…0025`). Primary keys are `UUID` (`uuid.uuid4`); timestamps are `DateTime(timezone=True)` with `server_default=func.now()`; money is `NUMERIC(18,2)`, quantities `NUMERIC(18,4)`, UOM factors `NUMERIC(18,6)`.

## 1. Migration inventory

| Migration | Contents |
|---|---|
| `0001_auth_audit_baseline` | users, roles, permissions, role_permissions, audit_logs |
| `0002_master_data` | categories, units_of_measure, brands, suppliers, customers, document_sequences, system_settings |
| `0003_stock_transactions` | products, stock_balances, stock_transactions(+items), stock_movements |
| `0004_pos_sales` | sales, sale_items, sale_returns(+items), payments |
| `0005_payment_debt_links` | customer_debts, supplier_debts + payment FK links |
| `0006` / `0007` | brands / uoms refinements |
| `0008_delivery_notes` | delivery_notes, delivery_note_sales, delivery_note_items |
| `0009_telegram_expiry_alerts` | telegram_expiry_alert_state |
| `0010_expenses` | expenses |
| `0011_sale_prices_uom_conversions_pos_extras` | product_sale_prices, products.uom_conversions (JSONB), sales.delivery_price |
| `0012_auth_profile_extras` | users.avatar, users.token_version, users.last_login_at |
| `0013_delivery_multi_invoice` | delivery note ↔ multi-invoice links |
| `0014_purchase_returns_stock_in_returned_qty` | purchase_returns(+items), stock_transaction_items.returned_quantity |
| `0015_stock_in_tax_discount` | stock_transactions.discount_amount / .tax_amount (purchase header adjustments) |
| `0016_document_currency` | currency + exchange_rate on stock_transactions, sales, expenses, supplier_debts, customer_debts |
| `0017_drop_invoice_pdf_object_key` | drops `sales.invoice_pdf_object_key` (no invoice files are ever stored) |
| `0018_product_fifo` | `products.fifo` costing option |
| `0019_delivery_driver_currency` | delivery note driver name + currency |
| `0020_delivery_fulfillment_fields` | delivery note date/vehicle/fee/receiver |
| `0021_barcode_first_product` | `products.sku` nullable; `products.barcode` NOT NULL (backfilled from sku, else `BAR-` id); `sale_items.sku` nullable |
| `0022_batch_fefo` | `batch_stock_balances` per (product, batch_no) remaining/received quantity, expiry, cost — written only by the canonical mutation service under row lock; FEFO sale allocation; outbound-line UOM entries |
| `0023_batch_lifecycle` | `products.track_batch` (batched Stock In lines MUST carry batch_no + expiry); batch lifecycle status; ledger links |
| `0024_batch_integrity` | DB check constraints: `batch_stock_balances.remaining_quantity >= 0` and `received_quantity >= remaining_quantity` |
| `0025_sale_price_version_uoms` | `product_sale_prices` + `batch_no`/`purchase_date`/`expiry_date` and the widened one-active-per-`(product, COALESCE(batch_no,''))` index; new `product_sale_price_uoms` (per-UOM price rows) backfilled from `uom_conversions` |

## 2. Identity & access

### users
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| full_name | varchar(200) | |
| email | varchar(255) UNIQUE | lowercased on create |
| password_hash | varchar(255) | Argon2 (`argon2-cffi`) |
| telegram_chat_id / telegram_verified | varchar(100) / bool | set via Telegram link code |
| role_id | FK → roles `RESTRICT` | one role per user |
| status | varchar(20) | `ACTIVE` / `DISABLED`; enforced in `get_current_user` |
| avatar | text nullable | data URL |
| token_version | int | embedded in JWTs; bump invalidates old tokens |
| last_login_at | timestamptz null | |

### roles
`id`, `name` UNIQUE, `description`, `is_system` (Administrator cannot be renamed/disabled), `status`.

### permissions / role_permissions
`permissions`: `code` UNIQUE (`module.action` or `ALL_PAGES`), `module`, `action`, `description` — synced from `PERMISSION_CATALOG` on setup/seed. `role_permissions`: PK (`role_id`,`permission_id`) both `CASCADE`.

## 3. Master data

### categories
`code` UNIQUE (uq_categories_code), `name`, `description`, `status`. Products FK `SET NULL` on delete.

### units_of_measure
`code` UNIQUE, `name`, `symbol` (varchar 20, shown on lists/invoices), `description`, `status`. Products FK `RESTRICT` (a UOM in use cannot be deleted; disable instead). Dev seeds: PCS, BOX, CAN, BTL, KG, PACK.

### brands
`code` UNIQUE, `name`, `description`, `logo_object_key` (varchar 500), `status`. Products FK `SET NULL`.

### suppliers
`code` UNIQUE (CUS-style `SUP-…` sequence), `name`, `company_name`, `phone`, `email`, `address`, `contact_person`, `note`, `status`.

### customers
`code` UNIQUE (`CUS-…` sequence), `name`, `phone`, `email`, `address`, `note`, `status`, `is_walk_in` (exactly one system walk-in row, cannot take debt). Indexes on name/phone.

## 4. Products & stock

### products
| Column | Type | Notes |
|---|---|---|
| sku | varchar(100) UNIQUE nullable | legacy internal code; barcode is the operational identifier (migration 0021) |
| barcode | varchar(100) UNIQUE NOT NULL | operational identifier; POS barcode lookup + product search; auto-issued `BAR-…` when omitted |
| name | varchar(200) | indexed |
| category_id / brand_id | FK nullable, `SET NULL` | |
| uom_id | FK → units_of_measure, NOT NULL, `RESTRICT` | base UOM, must be ACTIVE |
| cost_price / selling_price | NUMERIC(18,2) | selling_price mirrors the active sale-price version |
| minimum_stock | NUMERIC(18,4) | dashboard low-stock alert threshold |
| expiry_tracking | bool | gates expire operations & expiry alerts |
| uom_conversions | JSONB nullable | pricing rows `[{uom_id, uom_symbol, convert_uom_id, convert_uom_symbol, factor_to_base, sale_price, is_default_sale, cost_price?}]` |
| image_object_key | varchar(500) nullable | local-disk media |
| status | `ACTIVE`/`INACTIVE` | inactive products cannot be sold |
| note | text | |

### stock_balances
PK `product_id` (FK CASCADE). `quantity NUMERIC(18,4)`, `average_cost NUMERIC(18,2)`, `updated_at`. **Materialized cache — written only by `apply_stock_movement` under row lock.**

### product_sale_prices
`product_id` FK CASCADE, `sale_price` (default-sale/base UOM price), `effective_date`, `is_active`, `version`, `batch_no` (optional; NULL = general pricing scope), `purchase_date`, `expiry_date`, `created_by`. Constraints: UNIQUE (`product_id`,`version`); functional partial UNIQUE index on (`product_id`, `COALESCE(batch_no,'')`) `WHERE is_active` — exactly one active row per product + batch scope; the active version's default-sale UOM price is copied to the product's `selling_price` in the same transaction.

### product_sale_price_uoms
UOM price rows inside one price version: `price_version_id` FK CASCADE, `uom_id` FK RESTRICT, `uom_symbol` snapshot, `factor_to_base` NUMERIC(18,6), `sale_price` NUMERIC(18,2), `is_default_sale`. UNIQUE (`price_version_id`,`uom_id`). POS picks the price by the cart line's chosen UOM from the active version — batch-specific active version first, else the general active version.

### stock_transactions (header: Stock In / Adjustment / Damage / Expire)
`document_no` UNIQUE (STI/STA/DMG/EXP), `transaction_type` varchar(30), `supplier_id` FK `SET NULL`, `transaction_date`, `reference_no`, `note`, `discount_amount` + `tax_amount` NUMERIC(18,2) (purchase header adjustments: total = line subtotal − discount + tax), `currency` (`USD`|`KHR`) + `exchange_rate` NUMERIC(18,6) (KHR per 1 USD; 1 for USD), `status` (`CONFIRMED` — documents are created confirmed), `created_by` FK RESTRICT, `confirmed_by`. Index on `transaction_date`.

### stock_transaction_items
`stock_transaction_id` FK CASCADE, `product_id` FK RESTRICT, `quantity` (base UOM; signed negative for adjustment decrease), `unit_cost` (base-UOM cost), `system_quantity`/`actual_quantity` (adjustment only), `batch_no`, `expiry_date`, `uom_symbol` snapshot, `reason`, `line_total`, `returned_quantity` (cumulative purchase-returned qty), `created_at`.

### stock_movements (immutable ledger)
`product_id` FK RESTRICT, `movement_type` ∈ {`STOCK_IN`,`SALE`,`SALE_RETURN`,`PURCHASE_RETURN`,`ADJUSTMENT_IN`,`ADJUSTMENT_OUT`,`DAMAGE`,`EXPIRE`}, `quantity_delta` (signed, base UOM), `unit_cost`, `reference_type` + `reference_id` (polymorphic link), `document_no`, `batch_no`, `expiry_date`, `uom_symbol`, `note`, `created_by`. Indexes on `product_id`, `created_at`. **Rows are never updated or deleted.**

### purchase_returns / purchase_return_items
Header: `return_no` UNIQUE (PRT), `stock_transaction_id` FK RESTRICT (only confirmed Stock In), `supplier_id`, `return_date`, `refund_amount`, `debt_reduction`, `credit_amount`, `reason` (required), `created_by`. Items: `stock_transaction_item_id` FK RESTRICT, `product_id`, `quantity` (base UOM), `unit_cost`, `line_refund`.

## 5. Sales & payments

### sales
`invoice_no` UNIQUE (INV), `customer_id` FK RESTRICT, `sale_date`, `subtotal`, `discount_amount`, `grand_total`, `delivery_price` (included in grand total; no second stock-out), `paid_amount`, `debt_amount`, `currency` (`USD`|`KHR`) + `exchange_rate` NUMERIC(18,6) — every amount on the sale is in this currency (never mixed), `payment_status` (`PAID`/`PARTIAL`/`UNPAID`), `sale_status` (`COMPLETED`/`PARTIAL_RETURN`/`RETURNED`), `cashier_id` FK RESTRICT, `note`. Indexes on `sale_date`, `customer_id`. **No invoice file column** — printing is HTML-only in the browser (migration 0017).

### sale_items
`sale_id` FK CASCADE, `product_id` FK RESTRICT, snapshots `product_name`, `sku` (nullable — barcode is the identifier), `barcode`, `uom_id`, `uom_code`, `uom_symbol`, `factor_to_base`; `discount_percent`, `quantity` (selected UOM), `unit_price`, `unit_cost` (balance average at sale time), `discount_amount`, `line_total`, `returned_quantity`.

### sale_returns / sale_return_items
Header: `return_no` UNIQUE (SRT), `sale_id` FK RESTRICT, `return_date`, `refund_amount`, `reason`, `created_by`. Items: `sale_item_id` FK RESTRICT, `product_id`, `quantity` (sale UOM), `refund_amount` (pro-rata of line_total), `restock` bool.

### payments (immutable; all money movement)
`payment_no` UNIQUE (CDP/SDP), nullable FKs `sale_id`, `customer_id`, `supplier_id`, `customer_debt_id`, `supplier_debt_id` (all `SET NULL`); `payment_type` ∈ {`SALE_PAYMENT`, `CUSTOMER_DEBT_PAYMENT`, `SUPPLIER_DEBT_PAYMENT`, `STOCK_IN_PAYMENT`, `SUPPLIER_RETURN_CREDIT`}; `payment_method` (`CASH`, `BANK_QR`, `CUSTOMER_DEBT`, `CREDIT`, …); `amount`, `reference_no`, `note`, `created_by`. Payment rows are never edited or deleted.

### customer_debts / supplier_debts
`customer_id`/`supplier_id` FK RESTRICT; `sale_id` / `stock_transaction_id` FK RESTRICT; snapshot `invoice_no`/`document_no`; `original_amount`, `paid_amount`, `remaining_amount`, `currency` + `exchange_rate` (inherited from the source sale / Stock In document, so payments stay in the debt's currency), `due_date`, `status` (`UNPAID`/`PARTIAL`/`PAID`). Indexed on party + status. Updated only inside the paying/settling transaction under `FOR UPDATE`.

## 6. Delivery notes

### delivery_notes
`delivery_no` UNIQUE (DN), `customer_id` FK RESTRICT, `delivery_phone` + `delivery_location` (**NOT NULL**, required before Confirm/Out/Deliver), `delivered_at`, `status` (`DRAFT`/`CONFIRMED`/`OUT_FOR_DELIVERY`/`DELIVERED`/`CANCELLED`), `note`, `cancel_reason`, `created_by`. Indexes on status, customer, created_at.

### delivery_note_sales
UNIQUE (`delivery_note_id`,`sale_id`) — one note covers many invoices of the same customer; `invoice_no` snapshot for list/print.

### delivery_note_items
`delivery_note_id` FK CASCADE, `sale_id`, `sale_item_id` FK RESTRICT, `product_id`, `product_name`, `uom_symbol`, `qty_ordered`, `qty_to_deliver`, `qty_delivered`. On `DELIVERED`, `qty_delivered = qty_to_deliver` for all items. **No stock impact.**

## 7. Finance, settings, audit, sequences, alerts

### expenses
`expense_date`, `category`, `description`, `reference` (ledger Reference column), `amount`, `currency` (`USD`|`KHR`) + `exchange_rate` NUMERIC(18,6) (KHR rows are normalized to USD in the Finance report), `payment_method`, `created_by`. Indexes on `expense_date`, `created_by`. Backs the Finance Report only (no Expense page).

### system_settings
`group_name`, `key` UNIQUE (`group.key`), `value` JSONB (`{"v": …}`), `is_secret` (telegram.bot_token masked on read), `updated_by`. Catalog defaults in `administration/service.py`: groups `shop`, `currency`, `pos` (default_customer, allow_discount, maximum_discount, allow_negative_stock, receipt_footer), `stock` (low_stock_level, expiry_alert_1_days=90, expiry_alert_2_days=7, track_expiry), `telegram` (bot_token, enable_password_reset, verification_code_expiry=300, max_verification_attempts=5, stock_inquiry_enabled, payment_invoice_notify_enabled, expiry_alerts_enabled), `invoice`, `system` (language, date_format, timezone).

### audit_logs (append-only)
`user_id` FK `SET NULL`, `action`, `module`, `entity_type`, `entity_id`, `old_values`/`new_values` JSONB, `ip_address`, `user_agent`. Indexes on `created_at`, `user_id`. Never updated.

### document_sequences
`document_type` UNIQUE, `prefix`, `next_number` BIGINT, `number_length` (default 6), `reset_type` (nullable), `status`. Allocation = `SELECT … FOR UPDATE` + `PREFIX-%0{n}d` + increment, inside the caller's transaction. Missing sequences self-heal with a conflict-safe insert.

### telegram_expiry_alert_state
`product_id` FK RESTRICT, `batch_no` (nullable), `expiry_date`, `alert_level` (1=90d window, 2=7d window), `sent_at`. NULL-safe unique index `COALESCE(batch_no,'')` + spec unique constraint — one alert per (product, batch, expiry, level) so the daily scan never spams. Rows are written only when at least one Telegram delivery succeeded.

## 8. Relationship diagram (textual)

```
roles ──< users ──< audit_logs
roles ──< role_permissions >── permissions

categories ──< products >── brands            (SET NULL)
units_of_measure ──< products                 (RESTRICT)
products 1──1 stock_balances
products ──< product_sale_prices              (one active per batch scope)
product_sale_prices ──< product_sale_price_uoms
products ──< stock_transaction_items
products ──< stock_movements
products ──< sale_items
products ──< purchase_return_items / sale_return_items / delivery_note_items
products ──< telegram_expiry_alert_state

suppliers ──< stock_transactions ──< stock_transaction_items
stock_transactions ──< purchase_returns ──< purchase_return_items
stock_transactions 1──1 supplier_debts
suppliers ──< supplier_debts ──< payments

customers ──< sales ──< sale_items ──< sale_return_items >── sale_returns
sales 1──1 customer_debts; customers ──< customer_debts ──< payments
sales ──< payments ; sales ──< delivery_note_sales >── delivery_notes
delivery_notes ──< delivery_note_items >── sale_items
```

## 9. Concurrency & integrity rules enforced at the DB/service layer

- `FOR UPDATE` row locks: stock balances, document sequences, debts being paid, stock-in headers on purchase return, sale rows on delivery-note creation.
- Unique constraints: SKU, barcode, category/UOM/brand code, document numbers, sequence document_type, one active sale price, delivery-note↔sale pairs, expiry alert lots.
- `RESTRICT` deletes for anything with transaction history; products additionally require zero balance and zero movements before delete (service-level guard).
- All multi-table writes (sale completion, stock in, returns, payments) run in one async transaction committed by the owning service — rollback discards movements, sequences, debts and audit together.
- **Document-currency consistency**: all money columns on a document share its `currency`; debts inherit their source document's currency and exchange rate, so payments and reports never mix raw KHR and USD amounts (aggregates normalize via `exchange_rate`).
