/**
 * Page-access registry — every sidebar page this system has, with the
 * backend permission that unlocks the route and the full action block shown
 * in the Role permission matrix.
 *
 * Pages / actions are sourced from `PERMISSION_MATRIX_PAGES` so this file
 * never invents codes the backend catalog does not expose.
 */
import {
  PERMISSION_MATRIX_PAGES,
  type MatrixActionDefinition,
  type MatrixGroupId,
  type MatrixPageDefinition,
} from '~/utils/role/permissions'

export type PagePermission = {
  /** Stable page id (matches the permission-matrix row). */
  id: string
  /** Route path of the page. */
  path: string
  /** i18n label key for the page. */
  labelKey: string
  /** Sidebar / matrix group. */
  group: MatrixGroupId
  /** Backend permission code that unlocks the page (menu + route gate). */
  permission: string
  /** Every assignable action for this page block. */
  actions: readonly MatrixActionDefinition[]
}

/** Matrix page id → sidebar route path (only pages that exist in this app). */
const PAGE_ROUTES: Readonly<Record<string, string>> = {
  dashboard: '/',
  products: '/stock/products',
  stock_movements: '/stock/movements',
  pos: '/pos',
  delivery: '/delivery-notes',
  categories: '/setup/categories',
  brands: '/setup/brands',
  suppliers: '/setup/suppliers',
  customers: '/setup/customers',
  sales_report: '/reports/sales',
  purchase_report: '/reports/purchases',
  customer_debt_report: '/reports/customer-debts',
  supplier_debt_report: '/reports/supplier-debts',
  finance_report: '/reports/finance',
  users: '/administration/users',
  roles: '/administration/roles',
  document_sequences: '/administration/document-sequences',
  audit_logs: '/administration/audit-logs',
  settings: '/administration/settings',
}

/** Prefer View / Checkout as the route gate; otherwise the first action. */
function gatePermission(page: MatrixPageDefinition): string {
  const preferred = page.actions.find(action =>
    action.key === 'view'
    || action.key === 'checkout',
  )
  return (preferred || page.actions[0])!.permission
}

function toPagePermission(page: MatrixPageDefinition): PagePermission | null {
  const path = PAGE_ROUTES[page.value]
  if (!path || !page.actions.length) return null
  return {
    id: page.value,
    path,
    labelKey: page.labelKey,
    group: page.group,
    permission: gatePermission(page),
    actions: page.actions,
  }
}

/** Every page block this system ships, with its full action list. */
export const PAGE_PERMISSIONS: readonly PagePermission[] = PERMISSION_MATRIX_PAGES
  .map(toPagePermission)
  .filter((page): page is PagePermission => page !== null)

/** Route path → required permission (page gating in `useMenu`). */
export const ROUTE_PERMISSION: Record<string, string> = Object.fromEntries(
  PAGE_PERMISSIONS.map(page => [page.path, page.permission]),
)
