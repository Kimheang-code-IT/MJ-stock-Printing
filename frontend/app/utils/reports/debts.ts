import type { AppRecord } from '~/config/admin-seed'

/** Customer or supplier debt scope. */
export type DebtKind = 'customer' | 'supplier'

/**
 * The debt's own document currency always wins over any UI preference —
 * historical debts must never be re-displayed in the current preference.
 */
export function debtCurrency(row: AppRecord | null | undefined, fallback = 'USD'): string {
  return String(row?.currency || fallback || 'USD')
}

/**
 * True when every selected row belongs to the same party **and** currency,
 * i.e. it is safe to settle them in one backend operation (the backend settles
 * that party's open debts oldest-first and rejects overpayment).
 */
export function selectedDebtsShareScope(rows: readonly AppRecord[], kind: DebtKind): boolean {
  if (rows.length <= 1) return true
  const partyKey = (row: AppRecord) => String(kind === 'customer' ? row.customerId : row.supplierId)
  const firstParty = partyKey(rows[0]!)
  const firstCurrency = debtCurrency(rows[0])
  return rows.every(row => partyKey(row) === firstParty && debtCurrency(row) === firstCurrency)
}

/** Combined remaining balance of the selected open debts (2 dp). */
export function selectedDebtsTotal(rows: readonly AppRecord[]): number {
  return Math.round(rows.reduce((sum, row) => sum + Number(row.remainingAmount || 0), 0) * 100) / 100
}
