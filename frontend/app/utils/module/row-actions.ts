/**
 * Shared rules for list/detail row actions.
 *
 * Keeps the action menus in `WorkspaceView` and `DocumentView` consistent:
 * which collections can be hard-deleted, which carry an ACTIVE/INACTIVE-style
 * status toggle, and how to read/write that status across UI dialects.
 */

/** Collections whose backend exposes a dependency-checked DELETE endpoint. */
export const HARD_DELETE_COLLECTIONS = new Set<string>([
  'categories',
  'uoms',
  'brands',
  'products',
  'suppliers',
  'customers',
  'roles',
  'documentSequences',
])

/** Collections whose records carry an ACTIVE/INACTIVE-style status toggle. */
export const STATUS_TOGGLE_COLLECTIONS = new Set<string>([
  'categories',
  'uoms',
  'brands',
  'products',
  'suppliers',
  'customers',
  'users',
  'roles',
  'documentSequences',
])

const INACTIVE_VALUES = new Set(['inactive', 'disabled', 'deactivated'])

export function supportsHardDelete(collection?: string | null): boolean {
  return Boolean(collection && HARD_DELETE_COLLECTIONS.has(collection))
}

export function supportsStatusToggle(collection?: string | null): boolean {
  return Boolean(collection && STATUS_TOGGLE_COLLECTIONS.has(collection))
}

/** True only when the record is explicitly inactive/disabled/deactivated. */
export function isRecordInactive(status: unknown): boolean {
  return INACTIVE_VALUES.has(String(status ?? '').trim().toLowerCase())
}

/**
 * The status value the backend expects for a collection's active toggle.
 * Users use the `Active`/`Inactive` adapter dialect; roles use
 * `ACTIVE`/`DISABLED`; document sequences and the rest use the canonical
 * uppercase `ACTIVE`/`INACTIVE` values.
 */
export function statusValueFor(collection: string, active: boolean): string {
  if (collection === 'users') return active ? 'Active' : 'Inactive'
  if (collection === 'roles') return active ? 'ACTIVE' : 'DISABLED'
  return active ? 'ACTIVE' : 'INACTIVE'
}
