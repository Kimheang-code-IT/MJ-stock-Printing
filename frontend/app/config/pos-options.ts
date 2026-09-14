/** Shared Stock & POS option lists. */
export const PAYMENT_METHODS = ['Cash', 'Card', 'Mobile Payment', 'Bank Transfer', 'Credit'] as const

export const STOCK_OPERATION_TYPES = ['stock_in', 'adjustment', 'damage', 'expiry'] as const

export type StockOperationType = (typeof STOCK_OPERATION_TYPES)[number]

/** Movement-kind filter used by the stock history dialog on the Stock list
 *  (Current Stock is display-only and never opens the dialog). */
export type StockHistoryKind = 'stock_in' | 'stock_out' | 'damage'

export const STOCK_OPERATION_META: Record<StockOperationType, { label: string, icon: string, color: 'success' | 'primary' | 'warning' | 'error' }> = {
  // Stock In is labelled Purchase Stock — the full-page purchase flow is the
  // only stock-in surface (no Adjustment action on products).
  stock_in: { label: 'Purchase Stock', icon: 'i-lucide-package-plus', color: 'success' },
  adjustment: { label: 'Adjustment', icon: 'i-lucide-scale', color: 'primary' },
  damage: { label: 'Damage', icon: 'i-lucide-package-x', color: 'warning' },
  expiry: { label: 'Expiry', icon: 'i-lucide-calendar-x', color: 'error' },
}
