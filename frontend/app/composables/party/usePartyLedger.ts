import { unwrapApiData } from '~/repositories/http/response'
import { ApiEndpoints } from '~/utils/constants/api-endpoints'
import {
  normalizePartyHistory,
  type PartyHistory,
  type PartyKind,
} from '~/utils/party/ledger'

/**
 * Party-scoped, read-only history reader used by the customer/supplier detail
 * **History** tab. Projects the existing endpoints
 * (`/customers/{id}/purchase-history`, `/suppliers/{id}/history`) into UI rows.
 */
export function usePartyLedger() {
  const api = useApi()

  async function listHistory(kind: PartyKind, partyId: string): Promise<PartyHistory[]> {
    if (!partyId) return []
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
