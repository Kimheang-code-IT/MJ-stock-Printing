import { unwrapApiData } from '~/repositories/http/response'
import { ApiEndpoints } from '~/utils/constants/api-endpoints'
import {
  normalizePartyHistory,
  type PartyHistory,
  type PartyKind,
} from '~/utils/party/ledger'

function isMockMode(): boolean {
  try {
    return useRuntimeConfig().public.useMockData === true
  }
  catch {
    return false
  }
}

function num(value: unknown): number {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? Math.round((parsed + Number.EPSILON) * 100) / 100 : 0
}

/**
 * Mock mode: project the in-memory sales / stock-ins into the same History
 * row shape as the backend endpoints instead of issuing HTTP requests.
 */
async function listMockHistory(kind: PartyKind, partyId: string): Promise<PartyHistory[]> {
  const { useEntityRepository } = await import('~/repositories/index')
  const repo = useEntityRepository()
  if (kind === 'customer') {
    const result = await repo.list('sales', { limit: 1000 })
    return result.items
      .filter(row => String(row.customerId ?? '') === partyId)
      .map(row => ({
        id: String(row.id ?? ''),
        documentNo: String(row.invoiceNo ?? row.saleNo ?? ''),
        date: String(row.date ?? row.createdAt ?? '') || null,
        total: num(row.total ?? row.grandTotal),
        paidAmount: num(row.paidAmount),
        debtAmount: num(row.remaining ?? row.debtAmount),
        status: String(row.status ?? row.paymentStatus ?? ''),
      }))
  }
  const result = await repo.list('stockIns', { limit: 1000 })
  return result.items
    .filter(row => String(row.supplierId ?? '') === partyId)
    .map(row => ({
      id: String(row.id ?? ''),
      documentNo: String(row.purchaseNo ?? row.documentNo ?? ''),
      date: String(row.date ?? row.createdAt ?? '') || null,
      total: num(row.total),
      paidAmount: num(row.paidAmount),
      debtAmount: num(row.remaining),
      status: String(row.status ?? ''),
    }))
}

/**
 * Party-scoped, read-only history reader used by the customer/supplier detail
 * **History** tab. Projects the existing endpoints
 * (`/customers/{id}/purchase-history`, `/suppliers/{id}/history`) into UI rows;
 * mock mode reads the in-memory repository instead.
 */
export function usePartyLedger() {
  const api = useApi()

  async function listHistory(kind: PartyKind, partyId: string): Promise<PartyHistory[]> {
    if (!partyId) return []
    if (isMockMode()) return listMockHistory(kind, partyId)
    const endpoint = kind === 'customer'
      ? ApiEndpoints.CUSTOMER_HISTORY(partyId)
      : ApiEndpoints.SUPPLIER_HISTORY(partyId)
    const response = await api.get<unknown>(endpoint, {
      requestKey: `party-history:${kind}:${partyId}`,
      cancelPrevious: true,
      suppressErrorToast: true,
    })
    const rows = unwrapApiData<Record<string, unknown>[]>(
      response as Record<string, unknown>[] | { data: Record<string, unknown>[] },
    )
    return (Array.isArray(rows) ? rows : []).map(row => normalizePartyHistory(kind, row))
  }

  return { listHistory }
}
