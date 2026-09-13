import type { ProductBatchRow } from '~/repositories/contracts/entities'

/**
 * Batch lot display helpers (spec: batch/expiry + FEFO). Batch identity =
 * product + batch_no; expiry is an attribute of the lot. Batches without a
 * batch no (unbatched stock) are handled invisibly by the backend and are
 * never shown as selectable lots.
 */

export type BatchStatusUi = 'Active' | 'Expired' | 'Depleted'

/** Today as an ISO date (UTC) for expiry comparisons. */
export function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

/** UI status of a batch lot: Depleted (no stock) → Expired (past expiry with stock) → Active. */
export function batchStatusOf(batch: Pick<ProductBatchRow, 'remainingQty' | 'expiryDate'>): BatchStatusUi {
  if (Number(batch.remainingQty) <= 0) return 'Depleted'
  const expiry = String(batch.expiryDate ?? '').slice(0, 10)
  if (expiry && expiry < todayIso()) return 'Expired'
  return 'Active'
}

/** Badge color for a batch status value (`app.stock.batch*` labels). */
export function batchStatusColor(status: unknown): 'success' | 'warning' | 'neutral' {
  const value = String(status ?? '')
  if (value === 'Expired') return 'warning'
  if (value === 'Depleted') return 'neutral'
  return 'success'
}

/** Days from today to an ISO date (negative when past). */
export function daysUntil(isoDate: string | null | undefined): number | null {
  const text = String(isoDate ?? '').slice(0, 10)
  if (!text) return null
  const target = Date.parse(`${text}T00:00:00Z`)
  if (!Number.isFinite(target)) return null
  const today = Date.parse(`${todayIso()}T00:00:00Z`)
  return Math.round((target - today) / 86_400_000)
}

/** Stock list badge: expired (past) or expiring soon (≤ 90 days, spec lead 1). */
export function expiryBadge(isoDate: string | null | undefined): 'expired' | 'soon' | null {
  const days = daysUntil(isoDate)
  if (days == null) return null
  if (days < 0) return 'expired'
  if (days <= 90) return 'soon'
  return null
}