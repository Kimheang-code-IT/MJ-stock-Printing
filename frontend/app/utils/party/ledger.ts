/**
 * Party (customer / supplier) history helpers shared by the party detail
 * **History** tab. Pure projections of backend rows — no amounts are invented.
 */

export type PartyKind = 'customer' | 'supplier'

/** One sale (customer) or stock-in (supplier) history row. */
export interface PartyHistory {
  id: string
  documentNo: string
  date: string | null
  total: number
  paidAmount: number
  debtAmount: number
  status: string
  /** Whether the document still has goods to return to stock / supplier. */
  returnable: boolean
}

function asNumber(value: unknown): number {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? Math.round((parsed + Number.EPSILON) * 100) / 100 : 0
}

function asText(value: unknown): string {
  return String(value ?? '').trim()
}

/** `YYYY-MM-DD` day bucket for inclusive date comparisons. */
export function partyDay(value: unknown): string {
  return asText(value).slice(0, 10)
}

export function normalizePartyHistory(
  kind: PartyKind,
  row: Record<string, unknown>,
): PartyHistory {
  // A sale is returnable until fully returned; a Stock In until not confirmed.
  const saleStatus = asText(row.sale_status).toUpperCase()
  const returnable = kind === 'customer'
    ? saleStatus === 'COMPLETED' || saleStatus === 'PARTIAL_RETURN'
    : asText(row.status).toUpperCase() === 'CONFIRMED'
  return {
    id: asText(row.id),
    documentNo: asText(kind === 'customer' ? row.invoice_no : row.document_no),
    date: asText(row.sale_date ?? row.transaction_date) || null,
    total: asNumber(kind === 'customer' ? row.grand_total : row.total),
    paidAmount: asNumber(row.paid_amount),
    debtAmount: asNumber(row.debt_amount),
    status: asText(kind === 'customer' ? row.payment_status || row.sale_status : row.status),
    returnable,
  }
}
