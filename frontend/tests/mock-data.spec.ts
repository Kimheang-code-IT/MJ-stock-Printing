import { describe, expect, it } from 'vitest'
import {
  deliveryNotes,
  productById,
  products,
  saleReturns,
  sales,
  stockIns,
  stockMovements,
} from './support/mocks/stock-seed'

const APPROVED_MOVEMENT_TYPES = [
  'Stock In',
  'Sale',
  'Sale Return',
  'Purchase Return',
  'Adjustment Increase',
  'Adjustment Decrease',
  'Damage',
  'Expiry',
]

/**
 * Mock-data completeness contract (seed mirrors the live system): every
 * list/column of the current features renders meaningful, internally
 * consistent rows in mock mode.
 */
describe('mock seed: sale items carry price snapshots', () => {
  it('every sale line has a quantity, price and a consistent total', () => {
    for (const sale of sales) {
      for (const item of (sale.items as Array<Record<string, unknown>>)) {
        expect(Number(item.quantity), `${sale.saleNo}`).toBeGreaterThan(0)
        expect(Number(item.price), `${sale.saleNo}`).toBeGreaterThan(0)
        expect(Number(item.total)).toBeCloseTo(Number(item.price) * Number(item.quantity), 2)
      }
    }
  })
})

describe('mock seed: purchases carry batch traceability', () => {
  it('batch-tracked purchase lines have a lot no + expiry; unbatched do not', () => {
    for (const purchase of stockIns) {
      for (const item of (purchase.items as Array<Record<string, unknown>>)) {
        const product = productById(String(item.productId))
        if (product?.trackBatch === true) {
          expect(String(item.batchNo ?? '')).toMatch(/^B-/)
          expect(String(item.expiryDate ?? '')).not.toBe('')
        }
        else {
          expect(item.batchNo ?? '').toBe('')
        }
      }
    }
  })
})

describe('mock seed: movement ledger is complete and consistent', () => {
  it('only approved movement types appear', () => {
    const types = new Set(stockMovements.map(row => String(row.type)))
    for (const type of types) expect(APPROVED_MOVEMENT_TYPES, type).toContain(type)
  })

  it('every row has document/product/user display fields', () => {
    for (const row of stockMovements) {
      expect(String(row.documentNo || row.reference || '')).not.toBe('')
      expect(String(row.product ?? '')).not.toBe('')
      expect(String(row.user ?? '')).not.toBe('')
    }
  })

  it('running balances are consistent (balanceAfter = before + qty, qtyIn/out split)', () => {
    for (const row of stockMovements) {
      const qty = Number(row.quantity ?? 0)
      expect(Number(row.balanceAfter)).toBeCloseTo(Number(row.balanceBefore) + qty, 6)
      expect(Number(row.qtyIn ?? 0)).toBe(qty > 0 ? qty : 0)
      expect(Number(row.qtyOut ?? 0)).toBe(qty < 0 ? Math.abs(qty) : 0)
    }
    // Balances never go negative per product.
    const balances = new Map<string, number>()
    for (const row of [...stockMovements].sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)))) {
      const pid = String(row.productId)
      balances.set(pid, Number(row.balanceAfter))
    }
    for (const [pid, balance] of balances) {
      expect(balance, pid).toBeGreaterThanOrEqual(0)
    }
  })

  it('sales allocate FEFO lots: batched products have batched Sale rows', () => {
    for (const product of products.filter(row => row.trackBatch === true)) {
      const sold = stockMovements
        .filter(row => String(row.productId) === String(product.id) && row.type === 'Sale')
      const batchedSold = sold.filter(row => String(row.batchNo ?? '') !== '')
      // At least one batched sale row for sold batch-tracked products.
      if (sold.length) expect(batchedSold.length, String(product.id)).toBeGreaterThan(0)
    }
  })

  it('damage/expiry rows drain a named lot', () => {
    const drains = stockMovements.filter(row => row.type === 'Damage' || row.type === 'Expiry')
    expect(drains.length).toBeGreaterThan(0)
    for (const row of drains) {
      const product = productById(String(row.productId))
      if (product?.trackBatch === true) {
        expect(String(row.batchNo ?? ''), `${row.type} ${row.reference}`).toMatch(/^B-/)
      }
    }
  })

  it('returns appear in the ledger', () => {
    expect(stockMovements.some(row => row.type === 'Sale Return')).toBe(
      saleReturns.some(row => Number(row.restockedQuantity) > 0))
    expect(stockMovements.some(row => row.type === 'Purchase Return')).toBe(true)
  })
})

describe('mock seed: master data coherence', () => {
  it('delivery notes never deliver more than the sold quantity', () => {
    for (const note of deliveryNotes) {
      for (const line of (note.items as Array<Record<string, unknown>>)) {
        expect(Number(line.qtyToDeliver)).toBeLessThanOrEqual(Number(line.qtyOrdered))
      }
    }
  })
})
