import { describe, expect, it } from 'vitest'
import { stockModules } from '../app/config/stock-modules'
import { moduleDocumentTabs } from '../app/utils/module/document-tabs'
import { createMockStockQueryRepository } from '../app/repositories/mock/entities'
import { mockRecords } from '../app/mocks/db'
import { salePriceVersionSelection } from '../app/utils/stock/uom-conversions'

/**
 * Batch/lot + expiry + sale-price versioning (spec §5.9, §2.1.5):
 * - movements expose Batch No. + Expiry (global list + product history)
 * - batch lots derive from the ledger (received/remaining/expiry/status)
 * - sale price versions: exactly one POS-active, copies onto the product
 * - product detail: UOM & Sale Prices | Batches | Movements sections
 */

describe('product document sections (batches + pricing + movements)', () => {
  const productModule = stockModules.find(item => item.collection === 'products')!
  const tabs = moduleDocumentTabs(productModule)

  it('keeps the UOM & Sale Prices pricing section with version history', () => {
    const pricing = tabs.find(tab => tab.id === 'pricing')!
    const types = pricing.sections.flatMap(s => s.fields.map(f => f.type))
    expect(types).toContain('uom-conversions')
    expect(types).toContain('sale-price-history')
  })

  it('owns Track Expiry, Expire Date and the Batches panel on the General tab', () => {
    const general = tabs.find(tab => tab.id === 'general')!
    const fields = general.sections.flatMap(s => s.fields)
    expect(fields.map(f => f.key)).toContain('expiryTracking')
    expect(fields.map(f => f.key)).toContain('expiryDate')
    expect(fields.map(f => f.type)).toContain('batches')
  })

  it('adds the read-only Stock Movements section to the product detail', () => {
    const movements = tabs.find(tab => tab.id === 'movements')!
    expect(movements.sections.flatMap(s => s.fields.map(f => f.type))).toContain('product-movements')
    // Still no generic related-records tab (movements are a first-class tab).
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
    expect(versions.items.filter(row => row.isActive)).toHaveLength(1)
    // Newest version first.
    expect(versions.items[0]!.id).toBe(added.id)
  })

  it('re-activates an old version without deleting history', async () => {
    const versions = await repository.listSalePrices('prd1')
    const oldest = versions.items[versions.items.length - 1]!
    const activated = await repository.activateSalePrice('prd1', String(oldest.id))
    expect(activated.isActive).toBe(true)

    const after = await repository.listSalePrices('prd1')
    expect(after.items.filter(row => row.isActive)).toHaveLength(1)
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
    expect(selection).toMatchObject({ id: 'sp1', version: 3, batchNo: 'B-100', isActive: true, salePrice: 12.5 })
    expect(selection.uomPrices).toHaveLength(2)
    expect(selection.uomPrices[1]).toMatchObject({ uomSymbol: 'box', factorToBase: 12, salePrice: 140 })
  })

  it('normalizes a blank batch/price and defaults UOM rows to empty', () => {
    const selection = salePriceVersionSelection({ id: 'sp2', version: 1 })
    expect(selection.batchNo).toBeNull()
    expect(selection.isActive).toBe(false)
    expect(selection.salePrice).toBe(0)
    expect(selection.uomPrices).toEqual([])
  })
})
