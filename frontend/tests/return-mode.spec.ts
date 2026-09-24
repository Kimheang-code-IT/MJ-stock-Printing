import { describe, expect, it } from 'vitest'
import type { AppRecord } from '../app/config/admin-seed'
import type { SaleDetail } from '../app/repositories/contracts/entities'
import { saleReturnCartLines } from '../app/utils/pos/return'
import { buildPurchaseReturnLines, documentHasReturnableLines } from '../app/utils/reports/returns'

function product(overrides: Record<string, unknown> = {}): AppRecord {
  return {
    id: 'p1',
    name: 'Paracetamol',
    ...overrides,
  } as AppRecord
}

describe('POS sale return mode', () => {
  const sale: SaleDetail = {
    id: 'sale1',
    invoiceNo: 'INV-001',
    customerId: 'c1',
    customerName: 'Nita',
    currency: 'KHR',
    exchangeRate: 4100,
    items: [
      {
        id: 'item1',
        productId: 'p1',
        name: 'Paracetamol',
        quantity: 5,
        returnedQuantity: 0,
        unitPrice: 1000,
        lineTotal: 5000,
      },
      {
        id: 'item2',
        productId: 'p2',
        name: 'Fully Returned',
        quantity: 2,
        returnedQuantity: 2,
        unitPrice: 5000,
        lineTotal: 10000,
      },
    ],
  }

  it('preloads only returnable lines with original price, currency and qty', () => {
    const lines = saleReturnCartLines(sale, new Map([['p1', product()]]))
    expect(lines).toHaveLength(1)
    const line = lines[0]!
    expect(line.saleItemId).toBe('item1')
    expect(line.productId).toBe('p1')
    expect(line.quantity).toBe(5)
    expect(line.availableStock).toBe(5)
    expect(line.unitPrice).toBe(1000)
  })

  it('still loads the line when the product is unknown', () => {
    const lines = saleReturnCartLines(sale, new Map())
    expect(lines[0]!.quantity).toBe(5)
    expect(lines[0]!.name).toBe('Paracetamol')
  })

  it('uses only the still-returnable remainder when part of a line was returned', () => {
    const partiallyReturned: SaleDetail = {
      ...sale,
      items: [{ ...sale.items[0]!, quantity: 5, returnedQuantity: 2 }],
    }
    const lines = saleReturnCartLines(partiallyReturned, new Map())
    expect(lines[0]!.quantity).toBe(3)
    expect(lines[0]!.availableStock).toBe(3)
  })
})

describe('Purchase return mode lines', () => {
  const doc = {
    id: 'tx1',
    purchaseNo: 'PIN-00001',
    currency: 'KHR',
    exchangeRate: 4100,
    items: [
      { id: 'line1', productId: 'p1', name: 'Paracetamol', quantity: 10, returnedQuantity: 4, returnableQuantity: 6, price: 2 },
      { id: 'line2', productId: 'p2', name: 'Fully Returned', quantity: 3, returnedQuantity: 3, returnableQuantity: 0, price: 5 },
    ],
  } as unknown as AppRecord

  it('keeps original cost and defaults qty to the returnable amount', () => {
    const lines = buildPurchaseReturnLines(doc, new Map([['p1', product()]]))
    expect(lines).toHaveLength(1)
    const line = lines[0]!
    expect(line.lineId).toBe('line1')
    expect(line.unitAmount).toBe(2)
    expect(line.quantity).toBe(6)
    expect(line.amount).toBe(12)
    expect(line.returnableQuantity).toBe(6)
  })

  it('reports no returnable lines when everything was already returned', () => {
    expect(documentHasReturnableLines({ items: [{ quantity: 2, returnedQuantity: 2 }] } as unknown as AppRecord)).toBe(false)
  })
})
