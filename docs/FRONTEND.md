# Frontend — Nuxt 4 SPA (as implemented)

## 1. Stack & structure

Nuxt 4 (`nuxt generate` SSRG build), Vue 3 strict TypeScript, Nuxt UI v4 (+ `@tanstack/vue-table`, `@vueuse/core`), ECharts via `vue-echarts` (dashboard + finance chart only), Pinia (`@pinia/nuxt`) for auth/preferences/cached options, `@nuxtjs/i18n` with **en** and **km** locales (Khmer-first labels throughout `app/config/*`).

```
frontend/app/
├── components/
│   ├── common/        # field widgets (AppTextField, AppSelectMenuField, AppMoneyField,
│   │                  # AppDateField, AppImageUploadField, …), AppConfirmDialog/Host,
│   │                  # AppRolePermissionMatrix, AppExportDialog, AppFilterMenu,
│   │                  # AppLiveSearch, AppAccessAlertHost
│   ├── layout/        # AppHeader + useAppHeader + AppHeaderPageActions (shared sticky
│   │                  # top header), AppSlidebar, UserMenu, dialogs (About/Profile)
│   ├── module/        # ModulePage / WorkspaceView / DocumentView — generic CRUD UI
│   │                  # driven by ModuleConfig
│   ├── document/      # AppDocumentPage/Form/TabBar/MetaRail — document detail shells
│   ├── table/         # AppListTable, AppLineTable, AppRelatedRecords, cell helpers
│   ├── pos/           # PosProductBrowser, PosProductCard, PosCartPanel,
│   │                  # PosCheckoutPanel, PosOutstandingDebtDialog, PosPrintSizeDialog
│   ├── reports/       # DebtPaymentDialog, DebtPaySelectedDialog, DocumentDetailDialog
│   ├── party/         # HistoryPanel (customer/supplier detail History tab: status +
│   │                  # date filters, fit-height rows, per-row Edit)
│   ├── stock/         # BatchListPanel, PriceVersionsRail, PricingField,
│   │                  # ProductMovementsPanel, QtyHistoryDialog
│   ├── delivery/      # DeliveryNoteCreateFlow (shared create/edit delivery form)
│   ├── dashboard/     # AppKpiSection, AppSummaryCard, AppEChart (lazy-loaded), StockDashboardView
│   └── settings/      # SystemSettingsPage (schema-driven settings groups)
├── composables/       # useApi (auth refresh), useAuth, useMenu, useAppHeader,
│                      # useModule, useGlobalSearch, useAppBranding/Localization, …
├── config/            # modules.ts + admin/stock/delivery-modules.ts (page registry),
│                      # settings-schemas.ts, pos-options.ts, shared-options.ts
├── layouts/           # default (sidebar + header) and auth
├── middleware/        # auth.global.ts (session + per-page permission),
│                      # legacy-routes.global.ts (old rental URLs → new pages)
├── pages/             # one folder per sidebar entry (below)
├── repositories/      # http/* API adapters (real API only)
├── stores/            # auth.ts, preferences.ts, app-data.ts
├── types/stock-pos/   # shared domain types
└── utils/             # auth (tokens/session/permissions), print (invoice/delivery
                       # HTML printer), pos (cart/checkout math), format,
                       # role/permissions, security (files/url), uom-conversions
```

## 2. Session, auth & routing

- **Tokens** live in `sessionStorage` (per tab) mirrored to module memory — never in the readable profile cookie/localStorage (`utils/auth/tokens.ts`). The user profile is kept in a `auth_user` cookie + localStorage, but `isLoggedIn` requires live tokens.
- `useApi` attaches the bearer header, normalizes errors (`{statusCode, code, fieldErrors}`), performs **single-flight 401 refresh** (`utils/api/auth-refresher.ts`) then exactly one retry, re-fetches the profile after 403, and handles CSRF-safe same-origin checks.
- `middleware/auth.global.ts`: unauthenticated → `/auth/login?redirect=…`; authenticated users are bounced off auth pages; per-page `definePageMeta({ permission })` is checked with the Pinia store's `canAccessPage` (frontend-only UX; the backend re-checks everything). On denial: permission dialog, keep current page, or fall back to the first permitted landing route.
- `middleware/legacy-routes.global.ts` redirects legacy motorcycle-rental URLs to the new pages so no rental route is user-reachable.
- Auth pages (outside the sidebar): `/auth/login`, `/auth/setup` (initial administrator, once), `/auth/forgot-password`, `/auth/verify-code` (may be a step inside forgot-password), `/auth/reset-password` — reset codes arrive via Telegram deep links.

## 3. Generic module engine

Most CRUD pages are **configuration, not markup**: `app/config/stock-modules.ts`, `admin-modules.ts`, `delivery-modules.ts` and `modules.ts` describe each page (path, icon, sidebar group, permission id, collection, list columns, form fields/sections, filters, line tables, tabs, related record lists, actions, statuses). `ModulePage`/`WorkspaceView` render the list view; `[id].vue`/`new.vue` render the document view via `DocumentView`/`AppDocumentForm`. This keeps search, server-side pagination, loading/empty/error states, i18n (label/labelKm) and compact ERPNext-style layout consistent.

`stores/app-data.ts` caches option-list lookups (categories, UOMs, brands, suppliers, customers, roles) used by `optionsCollection`/`optionsEndpoint` fields.

## 4. Page-by-page documentation

Legend: **Perm** = `definePageMeta` permission id (frontend gate; backend codes in [API.md](API.md)). All list pages: sticky `AppHeader` with title/breadcrumbs/page actions, server-side search + filters, pagination, empty/error/permission states.

### Dashboard — `/` (`pages/index.vue`)
- **Purpose**: KPI overview for the pharmacy.
- **Data**: `GET /dashboard/summary` (period today/7d/30d/custom range).
- **Content**: KPI cards (sales, transactions, this-month sales, pending delivery notes, operating expenses, customer/supplier debt, damage/expiry loss, gross profit), ECharts sales trend series, low-stock and expiring-soon alert counts (vs `minimum_stock` and expiry windows), recent sales, recent stock activity, top products.
- **Perm**: `dashboard.view`. Refresh + period switcher in `AppHeaderPageActions`.

### Stock — `/stock` (`stock/index.vue`, `new.vue`, `[id].vue`, `stock/movements/index.vue`)
- **Purpose**: product master + current stock; the hub for all stock operations.
- **List columns**: image, SKU/barcode, name, category, brand, UOM, cost, price, current stock (opens QtyHistoryDialog), status. Filters: category, status, search.
- **Actions**: New product (`/stock/new`); per-row quick operations dialog → `POST /stock/operations` (`stock_in | adjustment | damage | expiry` with UOM + factor); product form with pricing-UOM table (`PricingField`, factor to base, per-UOM cost/sale price, default-sale flag), image upload (`/images/upload`), expiry tracking toggle, min-stock; SalePriceDialog (`/products/sale-prices` add/activate); CostHistoryDialog (`/stock/products/{id}/cost-history`); QtyHistoryDialog (`/stock/products/{id}/history?type=…`); delete guarded server-side.
- **Movements sub-page** (`/stock/movements`): immutable ledger (`GET /stock/movements`) with type/date/product filters.
- **Perm**: `products.view` (frontend id); backend: list `get_current_user`, mutations `product.create/update/delete`, operations `stock.in/adjust/damage/expire`.

### POS — `/pos` (`pos/index.vue`)
- **Purpose**: full-screen two-step selling workspace (chrome header hidden via `usePosChrome`).
- **Flow**: `PosProductBrowser` (search, barcode scan via `GET /pos/products/barcode/{code}`, category tiles, stock badges) → click/card adds `PosCartLine` (default UOM = pricing row flagged *Default sale*; switching UOM updates unit price/stock from that row, math in `utils/pos/cart.ts`) → `PosCartPanel` (qty, per-line % discount, editable unit price with a **sale-price history button** that opens `StockSalePriceDialog` for that product — view/add/activate a POS price version; on close the cart line re-applies the activated price for its current UOM, the base UOM always resolving to the POS-active `products.salePrice` mirror) → `PosCheckoutPanel` (customer select + quick create, payment method Cash/Bank-QR/Customer Debt, amount received, change, **OutstandingDebtDialog** listing the customer's open debts with checkboxes to settle from the tender (`includedDebtIds`), delivery price, due date for debt sales, note) → `POST /pos/sales/complete` → `PosPrintSizeDialog` (**A4 / A5 only** — the invoice prints in the sale's own currency, so there is no print-currency switch) → HTML print via `utils/print/invoice.ts` (hidden iframe, Khmer font stack, filler rows, buyer/seller signatures kept together; browser print only). **Edit mode**: opening `/pos?editSaleId=<id>` (from a Sales Report row or a customer History row) loads the original sale (`GET /pos/sales/{id}`) with all its lines at the original UOM, unit price, discount and customer; products can be added, and qty/price/discount are fully editable. Submit re-saves via `PATCH /pos/sales/{id}` (the backend reverses the old stock and re-applies the new lines — see [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) §16). **Return mode** (`/pos?returnSaleId=<id>`) still exists in the code (locked lines, Return Reason + Restock, `POST /pos/sales/{id}/return`) but is no longer linked from any UI. "Create delivery note" → `POST /pos/sales/{id}/delivery`. Checking **Delivery** at checkout opens `PosDeliveryInfoDialog` (phone, delivery location, delivery price; prefilled from the customer snapshot) — the captured phone/location navigate to `/delivery-notes/new?saleId=…&phone=…&location=…` as prefills and are stored on the delivery note header (Delivery Notes table shows Phone + Location).
- **Client guards**: discount controls disabled without `pos.discount`; debt sale requires a registered customer. Backend re-validates all of it. Walk-in checkout default: an untouched **Paid now** input pays the amount due in full (`checkoutPaidNow` in `utils/pos/checkout.ts` — `amount_received = due`), so walk-in cash sales submit with no customer and no typed tender; Credit is disabled for walk-in with a hint. Checkout customer field is **Name-only** (searchable; walk-in default) with an **Add new customer** quick-create dialog (`PosCustomerCreateDialog` → `POST /customers`, auto-selects the new customer); the Outstanding Debt control renders only when the selected customer has open debts.
- **Perm**: `pos.view` (frontend id); backend `pos.access`, print `pos.print`.

### Delivery — `/delivery-notes` (`index.vue`, `new.vue`, `[id].vue`)
> Sidebar label is **Delivery** (route and permission ids stay `/delivery-notes` + `delivery.*`). Sidebar order: Dashboard · POS · Delivery · Stock · Setup · Reports · Administration.
- **Purpose**: track delivery of sold goods; never re-moves stock.
- **List**: delivery no, customer, phone, location, date, status, items. Filters: status, customer, dates.
- **Create**: pick customer → `GET /delivery/deliverable-invoices` → select invoices (each row adds one invoice; the picker only offers that customer's deliverable invoices) → `GET /sales/{id}/deliverable-items` builds lines → phone + location (required) → `POST /delivery`.
- **Detail**: renders the **shared document page** (`DeliveryNoteCreateFlow` → `components/document/*`, same form as `/delivery-notes/new`) with General + Lines. Draft notes are editable and save via `PATCH /delivery/{id}` / confirm via status (`delivery.update`); non-drafts are read-only. The old status/print action buttons were removed from the detail page. Print payload: `GET …/{id}/print` → `utils/print/delivery-note.ts`.
- **Perm**: `delivery.view`; actions `delivery.create/update/confirm/deliver/cancel`.

### Setup — `/setup/*` (categories, uoms, brands, suppliers, customers)
Config-driven CRUD pages (list + `new.vue` + `[id].vue`):
- **Categories**: code (auto if blank), name, description, status; product count column; delete blocked server-side when referenced. Perm `categories.view`.
- **UOMs**: code, name, symbol (shown on lists/invoices), description, status; help text explains disable-instead-of-delete. Perm `uom.view`.
- **Brands**: code, name, description, status (no logo field). Perm `brand.view`.
- **Suppliers**: code, name, phone, location, status. Detail tabs are exactly **General** + **History**. History lists this supplier's Stock-In documents (status filter + date range, fit-height table that scrolls only the rows) with a per-row **Edit** action → `/reports/purchases/new?editPurchaseId=<id>` (perm `stock.in`). Perm `supplier.view`.
- **Customers**: code (CUS-…), name, phone, location, status; walk-in row is system-managed. Detail tabs are exactly **General** + **History**. History lists this customer's sales (status filter + date range, fit-height table) with a per-row **Edit** action → `/pos?editSaleId=<id>` (perm `pos.access`). Perm `customer.view`.

### Reports — `/reports/*`
- **Sales** (`sales/index.vue`, perm `reports.view`): filters customer/status/payment method/date; table of invoices; totals row; export CSV (`GET /reports/sales/export` via AppExportDialog). Per-invoice **Edit** action reuses the POS screen in edit mode (`/pos?editSaleId=<id>` → `PATCH /pos/sales/{id}`). The previous Return row action was removed.
- **Purchase** (`purchases/index.vue`, full-page create at `purchases/new.vue`): Stock In documents (`GET /reports/purchases`) with supplier, totals; the **Create** action routes to `/reports/purchases/new` (perm `stock.in`) — a schema-driven document page that posts the whole basket as **one** `POST /stock/in` (line UOM conversion, document currency USD/KHR + exchange rate, header subtotal/discount/tax/total footer, paid vs outstanding → supplier debt); per-document **Edit** action reuses the same page in edit mode (`/reports/purchases/new?editPurchaseId=<id>`, `PATCH /stock/in/{id}`); export. The previous Return row action was removed (both reports now expose **Edit** only).
- **Customer Debts** (`customer-debts/index.vue`): open/partial/paid debts, remaining totals, status chips, optional **Currency (USD/KHR)** filter; row **Pay** action (`DebtPaymentDialog`) plus multi-select **Pay Selected** (`DebtPaySelectedDialog`, one party + one currency, settles oldest-first); export.
- **Supplier Debts** (`supplier-debts/index.vue`): same pattern against purchases; export.
- **Finance** (`finance/index.vue`): income/expense **table (no chart on the ledger)** + summary cards (total sales, purchases, COGS, damage/expiry loss, gross profit, operating expenses, net result — formulas in [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) §14); ECharts trend where enabled; **Add Expense modal** gated by the expense permission (`POST /reports/finance/expenses`); expense rows editable in the ledger.

### Administration — `/administration/*`
- **Users** (`users/index.vue|new|[id]`): list (username, display name, email, role, Telegram, status, last login), form (password create-only, role select from options endpoint, Telegram linked automatically via bot), enable/disable, admin password reset. Perm `admin.users.view`.
- **Roles & Permissions** (`roles/*`): list; `AppRolePermissionMatrix` renders the **Permission matrix** — one row per module with an action-checkbox grid, a select-all header checkbox and Grant all / Clear all. Rows come from the live backend catalog `GET /admin/permissions`; when that request returns nothing or fails (e.g. offline) the matrix falls back to the **frontend mirror** (`ROLE_DOCUMENT_TYPES` in `utils/role/permissions.ts`) so the checkboxes always render. The separate **Page access** list was removed. `ALL_PAGES` reserved for Administrator. See [BACKEND.md](BACKEND.md) §8 for the residual drift notes. Perm `admin.roles.view`.
- **Document Sequences** (`document-sequences/*`): list of document types with prefix, next number, number length, status; editable (`PATCH /admin/document-sequences/{id}`); explanation of `PREFIX-000001` format. Perm `configuration.view`.
- **Audit Logs** (`audit-logs/index.vue`): read-only table (time, user, module, action, entity, IP, old/new values expandable), filters module/action/user/date. Perm `admin.audit_logs.view`.
- **Settings** (`settings/index.vue` → `SystemSettingsPage`): schema-driven groups from `config/settings-schemas.ts` — Shop (name/logo/phone/email/address), Currency, POS (default customer, allow discount, maximum discount %, allow negative stock, receipt footer), Stock (low-stock level, expiry alert 90/7-day windows, track expiry), Telegram (bot token secret, enable password reset, code expiry, max attempts, inquiry/notify toggles), Invoice (logo, footer, paper size, auto print), System (language en/km, date format, timezone). Secret fields masked. Perm `settings.app_config.view`.

## 5. Printing & exports

- **Invoices & delivery notes print via the browser** (`utils/print/html.ts`): hidden iframe, `document.fonts.ready` wait, Noto Sans Khmer font stack, invoice heading `វិក្កយបត្រ / INVOICE`, filler rows sized to the page-1 budget, A4/A5 (A5 scaled). The POS chooser shows **A4 / A5 only** and the invoice prints in the **record's own currency** (KHR sale → KHR, USD sale → USD) — no print-currency switch. Product-line cells are taller with Unit/Qty/Price/Discount centred; the totals + buyer/seller signatures form one atomic footer that stays on page 1 for short sales and moves to the last page when the lines overflow to 2–3 pages.
- **CSV exports** are streamed server-side (`/reports/*/export`) through `AppExportDialog` — no stored export files and no client-side CSV utility.

## 6. State & i18n conventions

- Pinia only where truly shared: `stores/auth.ts` (session/profile/permissions), `stores/preferences.ts` (locale, sidebar, theme-ish prefs), `stores/app-data.ts` (option caches).
- All user-facing strings go through i18n keys (`en.json`, `km.json`) with `labelKm` fields in module configs; the system-language setting and the locale switcher stay in sync.
- Money/dates rendered by `utils/format/format-service.ts` using the configured currency/timezone settings.
