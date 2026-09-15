import { describe, expect, it } from 'vitest'
import { documentDetailHrefFor, documentLinkTargetFor } from '../app/utils/module/document-links'

describe('documentDetailHrefFor', () => {
  it('Sale No → POS checkout view', () => {
    expect(documentDetailHrefFor('sales', 'saleNo', { id: 'sale-1', saleNo: 'INV-1' }))
      .toBe('/pos?viewSaleId=sale-1')
  })

  it('Purchase No → purchase detail view', () => {
    expect(documentDetailHrefFor('stockIns', 'purchaseNo', {
      id: 'sti-1',
      purchaseNo: 'STI-000001',
    })).toBe('/reports/purchases/new?viewPurchaseId=sti-1&purchaseNo=STI-000001')
  })

  it('returns null for unrelated columns', () => {
    expect(documentDetailHrefFor('sales', 'customer', { id: 'sale-1' })).toBeNull()
  })
})

describe('documentLinkTargetFor', () => {
  it('customer debt invoiceNo → sales report search', () => {
    expect(documentLinkTargetFor('customerDebts', 'invoiceNo', { invoiceNo: 'INV-9' }))
      .toEqual({ path: '/reports/sales', search: 'INV-9' })
  })
})
