import { describe, expect, it } from 'vitest'
import {
  checkoutChange,
  checkoutDeliveryFee,
  checkoutDepositTotal,
  checkoutDue,
  checkoutOutstanding,
  checkoutPaidNow,
  checkoutSaleNet,
} from '../app/utils/pos/checkout'

describe('POS checkout totals', () => {
  it('keeps grand total separate from existing debt payment (USD)', () => {
    // Subtotal 10 → Grand Total 10; deposit 2 must not inflate due.
    const grandTotal = checkoutSaleNet(10, 0)
    const deposit = checkoutDepositTotal([2])
    const due = checkoutDue(grandTotal, deposit)
    expect(grandTotal).toBe(10)
    expect(deposit).toBe(2)
    expect(due).toBe(10)
    expect(checkoutPaidNow(undefined, due, false)).toBe(10)
    expect(checkoutOutstanding(due, 10)).toBe(0)
    expect(checkoutChange(11, due)).toBe(1)
    expect(checkoutOutstanding(due, 11)).toBe(0)
  })

  it('builds sale net with delivery; deposit stays off the sale due', () => {
    const saleNet = checkoutSaleNet(100, 5)
    const deposit = checkoutDepositTotal([25, 15])
    const due = checkoutDue(saleNet, deposit)
    expect(saleNet).toBe(105)
    expect(deposit).toBe(40)
    expect(due).toBe(105)
    expect(checkoutOutstanding(due, 80)).toBe(25)
    expect(checkoutOutstanding(due, 105)).toBe(0)
    expect(checkoutChange(200, due)).toBe(95)
  })

  it('ignores delivery price when Delivery is not checked', () => {
    expect(checkoutDeliveryFee(false, 12)).toBe(0)
    expect(checkoutDeliveryFee(true, 12)).toBe(12)
    expect(checkoutSaleNet(100, checkoutDeliveryFee(false, 12))).toBe(100)
  })

  it('pays the grand total in full when Paid now is untouched (walk-in cash sale)', () => {
    expect(checkoutPaidNow(undefined, 9, false)).toBe(9)
    expect(checkoutOutstanding(9, checkoutPaidNow(undefined, 9, false))).toBe(0)
    expect(checkoutPaidNow(undefined, 0, false)).toBe(0)
    expect(checkoutPaidNow(Number.NaN, 9840, false)).toBe(9840)
  })

  it('allows overpay for change and credits nothing on Credit', () => {
    expect(checkoutPaidNow(80, 95, false)).toBe(80)
    expect(checkoutPaidNow(200, 95, false)).toBe(200)
    expect(checkoutChange(200, 95)).toBe(105)
    expect(checkoutPaidNow(undefined, 95, true)).toBe(0)
    expect(checkoutPaidNow(50, 95, true)).toBe(0)
  })

  it('keeps the same grand-total rules in KHR', () => {
    const grandTotal = checkoutSaleNet(41000, 0)
    const deposit = checkoutDepositTotal([8200])
    const due = checkoutDue(grandTotal, deposit)
    expect(grandTotal).toBe(41000)
    expect(due).toBe(41000)
    expect(checkoutPaidNow(undefined, due, false)).toBe(41000)
    expect(checkoutChange(41000, due)).toBe(0)
    expect(checkoutOutstanding(due, 30000)).toBe(11000)
  })
})
