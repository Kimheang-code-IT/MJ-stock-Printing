# Reports & Dashboard (as implemented)

All report endpoints live under `/api/v1/reports` (`app/modules/reports/`), accept the common list params (`q`, `page`, `limit`, `startDate`, `endDate`) plus report-specific filters, and return the standard `{data, meta:{page,limit,total}}` envelope. Each report has a CSV export twin (`…/export`) streamed server-side and consumed by the frontend `AppExportDialog`. All money math is `Decimal`/`NUMERIC`.

Permissions: `report.sales`, `report.purchase`, `report.customer_debt`, `report.supplier_debt`, `report.finance` (+ `expense.create` for adding expenses).

## 1. Sales Report — `/reports/sales` (+ `/export`) — page `/reports/sales`

- **Filters**: q (invoice no/customer), customer_id, product_id, category_id, cashier_id, payment_method (`CASH|BANK_QR|CUSTOMER_DEBT`), date range (defaults to today when no range given).
- **Grain**: one row per **sale item** (joined to its sale), showing invoice no, date, customer, cashier, product, qty (with UOM snapshot), unit price, discount, line total, payment method (latest `SALE_PAYMENT` for the sale), payment status.
- **Aggregates**: result-count + totals in `meta`; the page shows a totals row (subtotals, discounts, grand totals, debt).
- **Actions in UI**: print invoice (HTML), sale return dialog (`POST /pos/sales/{id}/return`), export CSV.

## 2. Purchase Report — `/reports/purchase` ≡ `/reports/purchases` (+ exports) — page `/reports/purchases`

- **Source**: `stock_transactions` of type `STOCK_IN` (status CONFIRMED) with items aggregated; supplier name/code joined.
- **Filters**: q (document no), supplier_id, date range.
- **Row**: document no (STI-…), date, supplier, reference no, note, item summary (product, base qty, UOM symbol, unit cost, batch, expiry), total, paid vs debt (via `supplier_debts`), created by.
- **Actions in UI**: **Create** routes to the full-page purchase flow `/reports/purchases/new` (perm `stock.in`) — one Stock In document with line UOM conversion, header subtotal/discount/tax/total, paid/outstanding footer, supplier debt for the unpaid balance; also reachable from the Stock In history dialog's Add button (`?productId=` preselected). Per-document **Purchase Return dialog** → `POST /stock/in/{id}/return` (per-line returnable qty = received − returned; refund splits into debt reduction + supplier credit), export CSV.

## 3. Customer Debt Report — `/reports/customer-debts` (+ export) — page `/reports/customer-debts`

- **Source**: `customer_debts` joined to sales/customers.
- **Filters**: q (invoice/customer name), customer_id, status (`UNPAID|PARTIAL|PAID`), date range.
- **Row**: invoice no, date, customer (name/code), original, paid, remaining, due date, status, created at. Overdue highlight when `due_date < today` and status ≠ PAID.
- **Summary**: total remaining across the filter.
- **Actions**: **DebtPaymentDialog** — pay a single debt (`POST /customers/{id}/debts/{debtId}/payments`) or customer-level pay-all (`POST /customers/{id}/payments`, oldest first); payment history per debt; export.

## 4. Supplier Debt Report — `/reports/supplier-debts` (+ export) — page `/reports/supplier-debts`

Mirror of §3 against `supplier_debts` joined to `stock_transactions`/`suppliers` (document no = STI-…). Pay endpoints: `POST /suppliers/{id}/debts/{debtId}/payments`, `POST /suppliers/{id}/payments`. Purchase returns already reduced debts appear with updated remaining amounts.

## 5. Finance Report — `/reports/finance`, `/finance/summary`, `/finance/entries`, `POST /finance/expenses` — page `/reports/finance`

Income is **derived read-only from POS data** (no duplicate income tables); the only user-managed rows are `expenses` (created via the Add Expense modal — no dedicated page, no `/expenses` route).

`GET /reports/finance?startDate&endDate` computes:

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

- **`/finance/entries`**: the income/expense ledger table (sales income rows, refund rows, expense rows with category/description/reference/amount/method/currency) with filters — an income/expense **table** per the approved UI; the chart slot (ECharts) exists but the ledger itself stays tabular.
- **`POST /finance/expenses`** (perm `report.finance` **and** `expense.create`): `expense_date` (≤ today), category (free-text or preset), description, optional reference, amount > 0, currency (`USD`\|`KHR`) + exchange rate, optional payment method. Audited; appears immediately in the ledger and the next summary.
- **Currency normalization**: every money document records `currency` + `exchange_rate` (KHR per 1 USD). Finance aggregates never mix raw amounts — a `_usd(expression, currency, rate)` SQL helper passes USD rows through and divides KHR rows by their stored rate (applies to sales, refunds, COGS, purchases, debts, expenses). Damage/expiry losses come from the movement cost ledger (per-mutation base-unit cost, no document currency) and stay as recorded.

## 6. Returns Reports — `/reports/sale-returns` · `/reports/purchase-returns`

Read-only history of the immutable return documents, backing the sidebar pages `/reports/customer-returns` and `/reports/supplier-returns` (both `ModuleWorkspaceView` pages, perm `reports.view` frontend / `report.sales` and `report.purchase` backend):

- **Customer returns** (`GET /reports/sale-returns`): one row per `sale_returns` document — return no (SRT-…), date, invoice no, customer, item count, restocked quantity, refund amount, reason, created by. Filters: q (return no/invoice/customer), date range.
- **Supplier returns** (`GET /reports/purchase-returns`): one row per `purchase_returns` document — return no (PRT-…), date, stock-in document no (STI-…), supplier, item count, refund amount split (debt reduction + credit), reason, created by. Filters: q, date range.
- Both are read-only (returns are created from the Sales/Purchase report return dialogs); `returned_quantity` on the source lines stays the single source of truth for returnable quantities.

## 7. Dashboard — `/dashboard/summary` — page `/`

One call returns (period = today / 7d / 30d / custom):

- **KPIs**: today's sales total + invoice count, this-month sales, pending delivery notes, operating expenses today (excludes purchase cost), customer & supplier debt totals, damage/expiry losses, refunds, gross profit/net figures.
- **Chart**: daily sales series for the selected period (ECharts via `AppEChart`).
- **Alerts**: low-stock product count (`quantity ≤ minimum_stock`), expiring/expired lot counts against the 90/7-day windows.
- **Lists**: recent sales, recent stock activity (movements), top products by revenue.

Cached briefly in Redis (`dashboard_cache_ttl_seconds`, 60 s); perm `dashboard.view`.

## 8. Exports & print

- CSV exports share the report's filters (`useServerExport` + `AppExportDialog`), stream `text/csv`, and are generated on the fly — **no export files are stored server-side**.
- Invoice and delivery-note printing are browser-print-only HTML flows (see [FRONTEND.md](FRONTEND.md) §5) with a USD/KHR print-currency switch in the print chooser — **no invoice PDFs are generated or stored anywhere**.
