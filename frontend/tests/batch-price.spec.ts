import { describe, expect, it } from 'vitest'
import { stockModules } from '../app/config/stock-modules'
import { moduleDocumentTabs } from '../app/utils/module/document-tabs'
import { createMockStockQueryRepository } from './support/repositories-mock/entities'
import { mockRecords } from './support/mocks/db'
import {
  buildBatchPricingCards,
  salePriceVersionSelection,
} from '../app/utils/stock/uom-conversions'

/**
 * Batch/lot + expiry + sale-price versioning (spec section 5.9 / 2.1.5):
 * Pricing tab uses a Batch rail (General + stock lots) beside the UOM table.
 */

describe('product document sections (batches + pricing + movements)', () => {
  const productModule = stockModules.find(item => item.collection === 'products')!
  const tabs = moduleDocumentTabs(productModule)

  it('keeps the UOM & Sale Prices pricing section (batch rail embedded)', () => {
    const pricing = tabs.find(tab => tab.id === 'pricing')!
    const types = pricing.sections.flatMap(s => s.fields.map(f => f.type))
    expect(types).toContain('uom-conversions')
    expect(types).not.toContain('sale-price-history')
  })

  it('hides the Stock Costing toggles and Expire Date (always on system-wide)', () => {
    const general = tabs.find(tab => tab.id === 'general')!
    const fields = general.sections.flatMap(s => s.fields)
    expect(fields.map(f => f.key)).not.toContain('expiryTracking')
    expect(fields.map(f => f.key)).not.toContain('trackBatch')
    expect(fields.map(f => f.key)).not.toContain('fifo')
    expect(fields.map(f => f.key)).not.toContain('expiryDate')
    expect(fields.map(f => f.type)).not.toContain('batches')
    expect(fields.map(f => f.type)).not.toContain('product-batches')
  })

  it('adds a Batches tab with product-batches management panel', () => {
    const batches = tabs.find(tab => tab.id === 'batches')!
    expect(batches.sections.flatMap(s => s.fields.map(f => f.type))).toContain('product-batches')
  })

  it('does not add a Stock Movements tab to the product detail', () => {
    expect(tabs.some(tab => tab.id === 'movements')).toBe(false)
    expect(tabs.some(tab => tab.id === 'related')).toBe(false)
  })

  it('shows Batch No. and Expiry on the global movements list', () => {
    const movements = stockModules.find(item => item.collection === 'stockMovements')!
    const keys = movements.columns.map(column => column.key)
    expect(keys).toContain('batchNo')
    expect(keys.indexOf('batchNo')).toBeGreaterThan(keys.indexOf('barcode'))
    expect(keys).toContain('expiryDate')
  })
})

describe('mock batch ledger (movement-derived lots)', () => {
  const repository = createMockStockQueryRepository()

  it('stamps Stock In movements of batch-tracked products with batch + expiry', async () => {
    const result = await repository.listProductHistory('prd1')
    const batched = result.items.filter(row => row.batchNo)
    expect(batched.length).toBeGreaterThan(0)
    for (const row of batched) {
      expect(row.batchNo).toMatch(/^B-/)
      expect(row.expiryDate).toBeTruthy()
    }
  })

  it('derives batch lots with received/remaining/expiry/status from the ledger', async () => {
    const result = await repository.listProductBatches('prd1')
    expect(result.items.length).toBeGreaterThan(0)
    for (const lot of result.items) {
      expect(lot.batchNo).toMatch(/^B-/)
      expect(Number(lot.receivedQty)).toBeGreaterThan(0)
      expect(lot.expiryDate).toBe('2027-03-15')
      expect(['Active', 'Expired', 'Depleted']).toContain(lot.status)
      expect(lot.currency).toBeTruthy()
      expect(typeof lot.pricingActive).toBe('boolean')
    }
  })
})

describe('sale price versioning (Product + UOM price, never batch cost)', () => {
  const repository = createMockStockQueryRepository()

  it('seeds exactly one active version equal to the product sale price', async () => {
    const product = mockRecords('products').find(row => String(row.id) === 'prd1')!
    const versions = await repository.listSalePrices('prd1')
    const active = versions.items.filter(row => row.isActive)
    expect(active).toHaveLength(1)
    expect(Number(active[0]!.salePrice)).toBe(Number(product.salePrice))
  })

  it('adds a new version as the only active one and copies it onto the product', async () => {
    const added = await repository.addSalePrice('prd1', { date: '2026-09-01', salePrice: 0.95 })
    expect(added.isActive).toBe(true)
    const product = mockRecords('products').find(row => String(row.id) === 'prd1')!
    expect(Number(product.salePrice)).toBe(0.95)

    const versions = await repository.listSalePrices('prd1')
    expect(versions.items.filter(row => row.isActive && !row.batchNo)).toHaveLength(1)
    expect(versions.items[0]!.id).toBe(added.id)
  })

  it('adds a batch-scoped price without overwriting the general product sale price', async () => {
    const product = mockRecords('products').find(row => String(row.id) === 'prd1')!
    const before = Number(product.salePrice)
    const added = await repository.addSalePrice('prd1', {
      date: '2026-09-03',
      salePrice: 1.25,
      batchNo: 'B-LOT-1',
      expiryDate: '2027-01-01',
    })
    expect(added.isActive).toBe(true)
    expect(added.batchNo).toBe('B-LOT-1')
    expect(Number(product.salePrice)).toBe(before)

    const versions = await repository.listSalePrices('prd1')
    expect(versions.items.filter(row => row.isActive && row.batchNo === 'B-LOT-1')).toHaveLength(1)
    expect(versions.items.filter(row => row.isActive && !row.batchNo).length).toBeGreaterThanOrEqual(1)
  })

  it('deactivates a batch-scoped price without removing history', async () => {
    const versions = await repository.listSalePrices('prd1')
    const batch = versions.items.find(row => row.batchNo === 'B-LOT-1' && row.isActive)
      || versions.items.find(row => row.batchNo)
    expect(batch).toBeTruthy()
    const deactivated = await repository.setSalePriceActive(String(batch!.id), false)
    expect(deactivated.isActive).toBe(false)
    const after = await repository.listSalePrices('prd1')
    expect(after.items.some(row => String(row.id) === String(batch!.id))).toBe(true)
  })

  it('re-activates an old version without deleting history', async () => {
    const versions = await repository.listSalePrices('prd1')
    const oldest = versions.items.filter(row => !row.batchNo).at(-1)!
    const activated = await repository.activateSalePrice('prd1', String(oldest.id))
    expect(activated.isActive).toBe(true)

    const after = await repository.listSalePrices('prd1')
    expect(after.items.filter(row => row.isActive && !row.batchNo)).toHaveLength(1)
    expect(after.items.length).toBe(versions.items.length)
  })

  it('rejects non-positive prices', async () => {
    await expect(repository.addSalePrice('prd1', { date: '2026-09-02', salePrice: 0 }))
      .rejects.toThrow()
  })
})

describe('sale price version selection (Pricing tab)', () => {
  it('maps a version history row into the Pricing-tab selection payload', () => {
    const selection = salePriceVersionSelection({
      id: 'sp1',
      version: 3,
      batchNo: 'B-100',
      isActive: true,
      salePrice: 12.5,
      uomPrices: [
        { uomId: 'u1', uomSymbol: 'pcs', factorToBase: 1, salePrice: 12.5, isDefaultSale: true },
        { uomId: 'u2', uomSymbol: 'box', factorToBase: 12, salePrice: 140 },
      ],
    })
    expect(selection).toMatchObject({
      id: 'sp1',
      version: 3,
      batchNo: 'B-100',
      scope: 'batch',
      isActive: true,
      salePrice: 12.5,
      editable: true,
    })
    expect(selection.uomPrices).toHaveLength(2)
    expect(selection.uomPrices[1]).toMatchObject({ uomSymbol: 'box', factorToBase: 12, salePrice: 140 })
  })

  it('normalizes a blank batch/price and defaults UOM rows to empty', () => {
    const selection = salePriceVersionSelection({ id: 'sp2', version: 1 })
    expect(selection.batchNo).toBeNull()
    expect(selection.scope).toBe('general')
    expect(selection.isActive).toBe(false)
    expect(selection.salePrice).toBe(0)
    expect(selection.uomPrices).toEqual([])
  })
})

describe('buildBatchPricingCards', () => {
  it('always leads with General and joins active lot prices', () => {
    const cards = buildBatchPricingCards({
      lots: [
        { batchNo: 'B-1', expiryDate: '2027-03-15', remainingQty: 10, unitCost: 0.5, status: 'Active' },
        { batchNo: 'B-2', expiryDate: '2026-12-01', remainingQty: 0, unitCost: 0.4, status: 'Depleted' },
      ],
      salePrices: [
        { id: 'g1', version: 2, batchNo: null, isActive: true, salePrice: 1, uomPrices: [] },
        { id: 'b1', version: 1, batchNo: 'B-1', isActive: true, salePrice: 1.2, uomPrices: [
          { uomId: 'u1', factorToBase: 1, salePrice: 1.2, isDefaultSale: true },
        ] },
      ],
      generalSalePrice: 1,
    })
    expect(cards[0]).toMatchObject({ key: 'general', scope: 'general', isPriceActive: true, salePrice: 1 })
    expect(cards).toHaveLength(3)
    expect(cards[1]).toMatchObject({
      key: 'batch:B-1',
      batchNo: 'B-1',
      expiryDate: '2027-03-15',
      isPriceActive: true,
      priceId: 'b1',
      salePrice: 1.2,
    })
    expect(cards[2]).toMatchObject({
      key: 'batch:B-2',
      isPriceActive: false,
      priceId: null,
    })
  })
})
