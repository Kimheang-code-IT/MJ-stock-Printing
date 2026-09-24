import { roundMoney } from '~/utils/pos/cart'

export type CheckoutDebtRow = Record<string, unknown> & {
  id: string
  date: string
  invoiceNo: string
  paidAmount: number
  remainingAmount: number
  paymentMethod: string
}

export function checkoutDeliveryFee(needsDelivery: boolean, deliveryPrice: number) {
  if (!needsDelivery) return 0
  return roundMoney(Math.max(0, Number(deliveryPrice) || 0))
}

/** Subtotal + delivery — the current sale only (never includes old debts). */
export function checkoutSaleNet(subtotal: number, deliveryPrice = 0) {
  return roundMoney(Math.max(0, subtotal + deliveryPrice))
}

/** Selected open invoices to settle at checkout (separate from sale grand total). */
export function checkoutDepositTotal(remainings: number[]) {
  return roundMoney(remainings.reduce((sum, value) => sum + (Number(value) || 0), 0))
}

/**
 * Amount due for THIS sale (grand total). Old-debt / deposit payments are
 * settled separately and must not inflate this figure.
 */
export function checkoutDue(saleNet: number, _depositTotal = 0) {
  return roundMoney(Math.max(0, Number(saleNet) || 0))
}

/** Remaining on the current sale after Paid now (never below zero). */
export function checkoutOutstanding(grandTotal: number, paidNow: number) {
  return roundMoney(Math.max(0, (Number(grandTotal) || 0) - (Number(paidNow) || 0)))
}

/** Cash change when Paid now exceeds the sale grand total. */
export function checkoutChange(paidNow: number, grandTotal: number) {
  return roundMoney(Math.max(0, (Number(paidNow) || 0) - Math.max(0, Number(grandTotal) || 0)))
}

/**
 * Paid-now amount for THIS sale only. An **untouched** input (undefined / NaN)
 * defaults to the grand total so a walk-in cash sale submits without typing
 * tender. Credit tenders nothing (balance becomes customer debt). Overpay is
 * allowed and surfaces as change — deposit / old-debt payments are never added.
 */
export function checkoutPaidNow(paidInput: number | undefined, grandTotal: number, isCredit: boolean): number {
  if (isCredit) return 0
  const due = roundMoney(Math.max(0, Number(grandTotal) || 0))
  if (paidInput == null) return due
  const typed = Number(paidInput)
  if (!Number.isFinite(typed)) return due
  return roundMoney(Math.max(0, typed))
}
