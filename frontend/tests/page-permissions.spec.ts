import { describe, expect, it } from 'vitest'
import { PAGE_PERMISSIONS, ROUTE_PERMISSION } from '../app/utils/role/page-permissions'
import {
  permissionRowsToFlatKeys,
  setFlatPermission,
} from '../app/utils/role/permissions'

describe('page access registry', () => {
  it('maps every sidebar page to a backend module.action code', () => {
    expect(PAGE_PERMISSIONS.length).toBeGreaterThan(15)
    for (const page of PAGE_PERMISSIONS) {
      expect(page.permission).toMatch(/^[a-z_]+\.[a-z_]+$/)
      expect(page.labelKey).toMatch(/^app\./)
    }
  })

  it('has unique route paths and a matching route→permission map', () => {
    const paths = PAGE_PERMISSIONS.map(page => page.path)
    expect(new Set(paths).size).toBe(paths.length)
    expect(ROUTE_PERMISSION).toEqual(
      Object.fromEntries(PAGE_PERMISSIONS.map(page => [page.path, page.permission])),
    )
    expect(ROUTE_PERMISSION['/reports/customer-debts']).toBe('report.customer_debt')
    expect(ROUTE_PERMISSION['/stock/products']).toBe('stock.view')
  })
})

describe('setFlatPermission (Page access toggles)', () => {
  it('adds a code and implies the module view when the module has one', () => {
    const rows = setFlatPermission([], 'supplier.debt.pay', true)
    const keys = permissionRowsToFlatKeys(rows)
    expect(keys).toContain('supplier.debt.pay')
    expect(keys).toContain('supplier.view')
  })

  it('does not invent a view for modules without one (report)', () => {
    const keys = permissionRowsToFlatKeys(setFlatPermission([], 'report.sales', true))
    expect(keys).toContain('report.sales')
    expect(keys).not.toContain('report.view')
  })

  it('removes a single action without touching the rest', () => {
    let rows = setFlatPermission([], 'stock.in', true)
    rows = setFlatPermission(rows, 'stock.adjust', true)
    expect(permissionRowsToFlatKeys(rows)).toEqual(
      expect.arrayContaining(['stock.view', 'stock.in', 'stock.adjust']),
    )
    rows = setFlatPermission(rows, 'stock.in', false)
    const keys = permissionRowsToFlatKeys(rows)
    expect(keys).toContain('stock.adjust')
    expect(keys).not.toContain('stock.in')
  })

  it('clears the module actions when a page view is removed', () => {
    let rows = setFlatPermission([], 'stock.in', true)
    rows = setFlatPermission(rows, 'stock.view', false)
    expect(permissionRowsToFlatKeys(rows).filter(key => key.startsWith('stock.'))).toEqual([])
  })
})
