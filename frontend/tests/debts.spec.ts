import { describe, expect, it } from 'vitest'
import { debtCurrency, isOpenDebt, openDebts, selectedDebtsShareScope, selectedDebtsTotal } from '../app/utils/reports/debts'
import type { AppRecord } from '../app/config/admin-seed'

function row(partial: Partial<AppRecord>): AppRecord {
  return partial as AppRecord
}

describe('debt currency + multi-pay scope', () => {
  it('uses the debt document currency over the UI fallback', () => {
    expect(debtCurrency(row({ currency: 'KHR' }), 'USD')).toBe('KHR')
    expect(debtCurrency(row({}), 'KHR')).toBe('KHR')
    expect(debtCurrency(row({}), '')).toBe('USD')
    expect(debtCurrency(null, 'KHR')).toBe('KHR')
  })

  it('allows batching only same customer + currency', () => {
    const c1 = row({ customerId: 'c1', currency: 'USD' })
    const c1b = row({ customerId: 'c1', currency: 'USD' })
    const c2 = row({ customerId: 'c2', currency: 'USD' })
    const c1Khr = row({ customerId: 'c1', currency: 'KHR' })

    expect(selectedDebtsShareScope([c1], 'customer')).toBe(true)
    expect(selectedDebtsShareScope([c1, c1b], 'customer')).toBe(true)
    expect(selectedDebtsShareScope([c1, c2], 'customer')).toBe(false)
    expect(selectedDebtsShareScope([c1, c1Khr], 'customer')).toBe(false)
  })

  it('scopes supplier rows by supplierId', () => {
    const s1 = row({ supplierId: 's1', currency: 'USD' })
    const s2 = row({ supplierId: 's2', currency: 'USD' })
    expect(selectedDebtsShareScope([s1], 'supplier')).toBe(true)
    expect(selectedDebtsShareScope([s1, s2], 'supplier')).toBe(false)
  })

  it('sums the selected remaining balance without float drift', () => {
    expect(selectedDebtsTotal([
      row({ remainingAmount: 0.1 }),
      row({ remainingAmount: 0.2 }),
    ])).toBe(0.3)
    expect(selectedDebtsTotal([
      row({ remainingAmount: 12 }),
      row({ remainingAmount: 0.5 }),
    ])).toBe(12.5)
    expect(selectedDebtsTotal([])).toBe(0)
  })
})

describe('open debt filtering', () => {
  it('keeps unpaid and partially paid debts', () => {
    expect(isOpenDebt(row({ remainingAmount: 10, status: 'UNPAID' }))).toBe(true)
    expect(isOpenDebt(row({ remainingAmount: 3.5, status: 'PARTIAL' }))).toBe(true)
  })

  it('drops fully settled debts', () => {
    expect(isOpenDebt(row({ remainingAmount: 0, status: 'PAID' }))).toBe(false)
    expect(isOpenDebt(row({ remainingAmount: 0, status: 'UNPAID' }))).toBe(false)
    expect(isOpenDebt(row({ status: 'PAID' }))).toBe(false)
    expect(isOpenDebt(null)).toBe(false)
  })

  it('filters a debt list down to open rows', () => {
    const rows = [
      row({ remainingAmount: 0, status: 'PAID' }),
      row({ remainingAmount: 12, status: 'PARTIAL' }),
      row({ remainingAmount: 5, status: 'UNPAID' }),
    ]
    expect(openDebts(rows).map(item => item.remainingAmount)).toEqual([12, 5])
  })
})
