import type { AppRolePermissionRow } from '~/types/stock-pos/entities'

/**
 * Frontend mirror of the backend permission catalog
 * (`backend/app/core/permissions.py`). `permissionPrefix` is the backend
 * **module** code; actions are the backend action names (including dotted
 * actions such as `debt.pay`). The Role & Permissions matrix renders the live
 * catalog from `GET /admin/permissions`; this mirror powers row labels,
 * role seeding and the permission-ID validation test.
 */
export interface RoleDocumentTypeDefinition {
  /** Backend module code (also the matrix row key / `documentType`). */
  value: string
  labelKey: string
  permissionPrefix: string
  actions: readonly string[]
}

export const ROLE_DOCUMENT_TYPES: readonly RoleDocumentTypeDefinition[] = [
  { value: 'dashboard', labelKey: 'app.pages.dashboard', permissionPrefix: 'dashboard', actions: ['view', 'view_profit'] },
  { value: 'category', labelKey: 'app.nav.categories', permissionPrefix: 'category', actions: ['view', 'create', 'update', 'delete'] },
  { value: 'uom', labelKey: 'app.nav.uoms', permissionPrefix: 'uom', actions: ['view', 'create', 'update', 'delete'] },
  { value: 'brand', labelKey: 'app.nav.brands', permissionPrefix: 'brand', actions: ['view', 'create', 'update', 'delete'] },
  { value: 'stock', labelKey: 'app.nav.stock', permissionPrefix: 'stock', actions: ['view', 'in', 'adjust', 'damage', 'expire'] },
  { value: 'product', labelKey: 'app.pages.products', permissionPrefix: 'product', actions: ['create', 'update', 'delete'] },
  { value: 'supplier', labelKey: 'app.nav.suppliers', permissionPrefix: 'supplier', actions: ['view', 'create', 'update', 'delete', 'debt.pay'] },
  { value: 'pos', labelKey: 'app.nav.pos', permissionPrefix: 'pos', actions: ['access', 'discount', 'debt_sale', 'print'] },
  { value: 'customer', labelKey: 'app.nav.customers', permissionPrefix: 'customer', actions: ['view', 'create', 'update', 'delete', 'debt.pay'] },
  { value: 'delivery', labelKey: 'app.nav.deliveryNotes', permissionPrefix: 'delivery', actions: ['view', 'create', 'update', 'confirm', 'deliver', 'cancel'] },
  { value: 'report', labelKey: 'app.nav.reports', permissionPrefix: 'report', actions: ['sales', 'purchase', 'customer_debt', 'supplier_debt', 'finance'] },
  { value: 'expense', labelKey: 'app.reports.addExpense', permissionPrefix: 'expense', actions: ['create'] },
  { value: 'user', labelKey: 'app.pages.users', permissionPrefix: 'user', actions: ['manage'] },
  { value: 'role', labelKey: 'app.pages.roles', permissionPrefix: 'role', actions: ['manage'] },
  { value: 'sequence', labelKey: 'app.pages.documentSequences', permissionPrefix: 'sequence', actions: ['manage'] },
  { value: 'audit', labelKey: 'app.pages.auditLogs', permissionPrefix: 'audit', actions: ['view'] },
  { value: 'settings', labelKey: 'app.pages.settings', permissionPrefix: 'settings', actions: ['manage'] },
] as const

/** Backend action names are free-form (e.g. `debt.pay`), so keep them strings. */
export type RolePermissionAction = string

export const SUPER_ADMIN_PERMISSION = 'ALL_PAGES'

/** Every permission code in the frontend mirror (tests / ALL_PAGES expansion). */
export function allFrontendPermissionCodes(): string[] {
  return ROLE_DOCUMENT_TYPES.flatMap(def => def.actions.map(action => `${def.permissionPrefix}.${action}`))
}

function normalizeActions(actions: readonly string[] | null | undefined): string[] {
  const seen = new Set<string>()
  for (const action of actions || []) {
    const value = String(action || '').trim()
    if (value) seen.add(value)
  }
  return [...seen]
}

/** Merge duplicate rows and trim action noise; order follows the catalog. */
export function normalizePermissionRows(
  rows: readonly AppRolePermissionRow[] | null | undefined,
  includeEmpty = true,
): AppRolePermissionRow[] {
  const byType = new Map<string, AppRolePermissionRow>()
  for (const row of rows || []) {
    const documentType = String(row.documentType || '').trim()
    if (!documentType) continue
    const actions = normalizeActions(row.actions)
    const existing = byType.get(documentType)
    byType.set(documentType, {
      id: row.id || `perm_${documentType}`,
      documentType,
      onlyIfCreator: false,
      level: 0,
      actions: existing ? normalizeActions([...existing.actions, ...actions]) : actions,
    })
  }
  const ordered = ROLE_DOCUMENT_TYPES
    .filter(def => byType.has(def.value))
    .map(def => byType.get(def.value)!)
  const extras = [...byType.values()].filter(row => !ROLE_DOCUMENT_TYPES.some(def => def.value === row.documentType))
  const all = [...ordered, ...extras]
  return includeEmpty ? all : all.filter(row => row.actions.length > 0)
}

/** Toggle one action; non-view actions imply view when the module defines it. */
export function setPermissionAction(
  row: AppRolePermissionRow,
  action: string,
  enabled: boolean,
  hasViewAction = true,
): AppRolePermissionRow {
  const actions = new Set(normalizeActions(row.actions))
  if (enabled) {
    actions.add(action)
    if (action !== 'view' && hasViewAction) actions.add('view')
  }
  else if (action === 'view') {
    actions.clear()
  }
  else {
    actions.delete(action)
  }
  return { ...row, actions: normalizeActions([...actions]), onlyIfCreator: false }
}

/**
 * Toggle one flat backend code (`module.action`) on the matrix rows, applying
 * the same view-dependency rules as `setPermissionAction`. Backs the matrix
 * **Page access** list, where each page maps to exactly one code.
 */
export function setFlatPermission(
  rows: readonly AppRolePermissionRow[] | null | undefined,
  code: string,
  enabled: boolean,
): AppRolePermissionRow[] {
  const separator = code.indexOf('.')
  if (separator <= 0) return normalizePermissionRows(rows, true)
  const module = code.slice(0, separator)
  const action = code.slice(separator + 1)
  const definition = ROLE_DOCUMENT_TYPES.find(item => item.value === module)
  const hasView = Boolean(definition?.actions.includes('view'))
  const normalized = normalizePermissionRows(rows, true)
  const found = normalized.find(row => row.documentType === module)
  const target: AppRolePermissionRow = found || {
    id: `perm_${module}`,
    documentType: module,
    onlyIfCreator: false,
    level: 0,
    actions: [],
  }
  const updated = setPermissionAction(target, action, enabled, hasView)
  const next = found
    ? normalized.map(row => (row.documentType === module ? updated : row))
    : [...normalized, updated]
  return normalizePermissionRows(next, true)
}

/** Matrix rows → flat backend codes (`module.action`). */
export function permissionRowsToFlatKeys(rows: AppRolePermissionRow[]): string[] {  const keys = new Set<string>()
  for (const row of normalizePermissionRows(rows, false)) {
    for (const action of row.actions) keys.add(`${row.documentType}.${action}`)
  }
  return [...keys].sort()
}

/** Flat backend codes → matrix rows (module = first dotted segment). */
export function flatKeysToPermissionRows(keys: readonly string[]): AppRolePermissionRow[] {
  if (keys.includes(SUPER_ADMIN_PERMISSION)) {
    return normalizePermissionRows(ROLE_DOCUMENT_TYPES.map(def => ({
      id: `perm_${def.value}`,
      documentType: def.value,
      onlyIfCreator: false,
      level: 0,
      actions: [...def.actions],
    })), true)
  }
  const byType = new Map<string, string[]>()
  for (const key of keys) {
    const separator = key.indexOf('.')
    if (separator <= 0) continue
    const module = key.slice(0, separator)
    const action = key.slice(separator + 1)
    if (!action) continue
    byType.set(module, [...(byType.get(module) || []), action])
  }
  return normalizePermissionRows([...byType.entries()].map(([documentType, actions]) => ({
    id: `perm_${documentType}`,
    documentType,
    onlyIfCreator: false,
    level: 0,
    actions,
  })), true)
}

export type SeedRolePermissionMode = 'all' | 'staff' | 'viewer'

/** Fixture rows for seeded roles (Administrator / Store Staff / Report Viewer). */
export function seedRolePermissionRows(mode: SeedRolePermissionMode): AppRolePermissionRow[] {
  const restricted = new Set(['user', 'role', 'sequence', 'settings', 'audit'])
  return normalizePermissionRows(ROLE_DOCUMENT_TYPES.map((def) => {
    let actions: string[] = [...def.actions]
    if (mode === 'viewer') actions = actions.filter(action => action === 'view')
    else if (mode === 'staff' && restricted.has(def.value)) actions = []
    return { id: `perm_${def.value}`, documentType: def.value, onlyIfCreator: false, level: 0, actions }
  }))
}
