import type { PaginationState } from '@tanstack/vue-table'
import { TABLE_VIRTUALIZE_AFTER } from '~/utils/table/theme'

type Translate = (key: string, values?: Record<string, unknown>) => string

/** How a sortable column's values are compared (drives the menu wording). */
export type ListTableSortKind = 'date' | 'number' | 'text'

/** A sortable field offered in the toolbar sort menu. */
export type ListTableSortOption = {
  key: string
  label: string
  kind: ListTableSortKind
}

/** The active sort selection (`null` = original order). */
export type ListTableSort = {
  key: string
  dir: 'asc' | 'desc'
  kind: ListTableSortKind
}

/** Column keys that read as a date/time value (camelCase: date, createdAt, occurredAt…). */
const LIST_TABLE_DATE_KEY = /(?:[Dd]ate|[Tt]ime|At|Day)$/
/** Column keys that read as a document/numbering value (saleNo, invoiceNo, reference…). */
const LIST_TABLE_NO_KEY = /(?:no|number|code|reference|ref)$/i

function listTableColumnKey(column: unknown): string {
  if (!column || typeof column !== 'object') return ''
  const candidate = column as { accessorKey?: unknown, id?: unknown }
  if (typeof candidate.accessorKey === 'string') return candidate.accessorKey
  if (typeof candidate.id === 'string') return candidate.id
  return ''
}

/** Best-effort fallback: pick the first date and document-number column. */
export function deriveListTableSortOptions(columns: readonly unknown[]): Array<{ key: string, kind: ListTableSortKind }> {
  const keys = columns
    .map(listTableColumnKey)
    .filter(key => key && !key.startsWith('__'))
  const dateKey = keys.find(key => LIST_TABLE_DATE_KEY.test(key))
  const noKey = keys.find(key => key !== dateKey && LIST_TABLE_NO_KEY.test(key))
  const options: Array<{ key: string, kind: ListTableSortKind }> = []
  if (dateKey) options.push({ key: dateKey, kind: 'date' })
  if (noKey) options.push({ key: noKey, kind: 'number' })
  return options
}

export function compareListTableValues(a: unknown, b: unknown, kind: ListTableSortKind): number {
  if (kind === 'number') {
    const na = Number(a)
    const nb = Number(b)
    if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb
  }
  if (kind === 'date') {
    const ta = Date.parse(String(a ?? ''))
    const tb = Date.parse(String(b ?? ''))
    if (!Number.isNaN(ta) && !Number.isNaN(tb)) return ta - tb
  }
  return String(a ?? '').localeCompare(String(b ?? ''), undefined, { numeric: true, sensitivity: 'base' })
}

/** Returns a copy of `rows` sorted by `sort`; original order when unset. */
export function applyListTableSort<T extends Record<string, unknown>>(
  rows: T[],
  sort: ListTableSort | null | undefined,
): T[] {
  if (!sort?.key) return rows
  const dir = sort.dir === 'desc' ? -1 : 1
  const { key, kind } = sort
  return [...rows].sort((a, b) => compareListTableValues(a[key], b[key], kind) * dir)
}

/** Header counter: "6 of 6" for the row-action column. */
export function listTablePageSummary(
  t: Translate,
  total: number,
  pagination: Pick<PaginationState, 'pageIndex' | 'pageSize'>,
) {
  if (!total) return t('app.ui.ofZero')
  const start = pagination.pageIndex * pagination.pageSize
  const end = Math.min(start + pagination.pageSize, total)
  const shown = Math.max(0, end - start)
  return t('app.ui.of', { shown, total })
}

export function listTableSelectedIds(selection: Record<string, boolean>) {
  return Object.keys(selection).filter(id => selection[id])
}

export function listTableVirtualize(total: number, pageSize: number) {
  if (total < TABLE_VIRTUALIZE_AFTER && pageSize < TABLE_VIRTUALIZE_AFTER) return false as const
  return {
    estimateSize: 48,
    overscan: 12,
  }
}
