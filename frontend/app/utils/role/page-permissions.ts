/**
 * Page-access registry — the single source of truth for which backend
 * permission each sidebar page requires. Used by `useMenu` (route gating) and
 * the Role & Permissions matrix ("Page access" list).
 *
 * Each entry maps a **page/route** to the exact backend permission code the
 * page is gated by (the same code `definePageMeta` uses), so the matrix can
 * grant page access without the frontend/backend permission drift.
 */
export type PagePermission = {
  /** Route path of the page. */
  path: string
  /** i18n label key for the page. */
  labelKey: string
  /** Backend permission code that unlocks the page. */
  permission: string
}

export const PAGE_PERMISSIONS: readonly PagePermission[] = [
  { path: '/', labelKey: 'app.nav.dashboard', permission: 'dashboard.view' },
  { path: '/stock/products', labelKey: 'app.stock.tabProducts', permission: 'stock.view' },
  { path: '/stock/movements', labelKey: 'app.stock.tabMovements', permission: 'stock.view' },
  { path: '/pos', labelKey: 'app.nav.pos', permission: 'pos.access' },
  { path: '/delivery-notes', labelKey: 'app.nav.deliveryNotes', permission: 'delivery.view' },
  { path: '/setup/categories', labelKey: 'app.nav.categories', permission: 'category.view' },
  { path: '/setup/uoms', labelKey: 'app.nav.uoms', permission: 'uom.view' },
  { path: '/setup/brands', labelKey: 'app.nav.brands', permission: 'brand.view' },
  { path: '/setup/suppliers', labelKey: 'app.nav.suppliers', permission: 'supplier.view' },
  { path: '/setup/customers', labelKey: 'app.nav.customers', permission: 'customer.view' },
  { path: '/reports/sales', labelKey: 'app.pages.salesReport', permission: 'report.sales' },
  { path: '/reports/purchases', labelKey: 'app.pages.purchaseReport', permission: 'report.purchase' },
  { path: '/reports/customer-debts', labelKey: 'app.pages.customerDebtReport', permission: 'report.customer_debt' },
  { path: '/reports/supplier-debts', labelKey: 'app.pages.supplierDebtReport', permission: 'report.supplier_debt' },
  { path: '/reports/finance', labelKey: 'app.pages.financeReport', permission: 'report.finance' },
  { path: '/administration/users', labelKey: 'app.pages.users', permission: 'user.manage' },
  { path: '/administration/roles', labelKey: 'app.pages.roles', permission: 'role.manage' },
  { path: '/administration/document-sequences', labelKey: 'app.pages.documentSequences', permission: 'sequence.manage' },
  { path: '/administration/audit-logs', labelKey: 'app.pages.auditLogs', permission: 'audit.view' },
  { path: '/administration/settings', labelKey: 'app.pages.settings', permission: 'settings.manage' },
] as const

/** Route path → required permission (page gating in `useMenu`). */
export const ROUTE_PERMISSION: Record<string, string> = Object.fromEntries(
  PAGE_PERMISSIONS.map(page => [page.path, page.permission]),
)
