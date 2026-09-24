import type { AppRecord } from '~/config/admin-seed'
import { roundMoney } from '~/utils/pos/cart'

export type ReturnDocumentKind = 'sale' | 'purchase'

export type ReturnLineDraft = {
  lineId: string
  productId: string
  name: string
  soldQty: number
  returnedQty: number
  returnableQty: number
  unitAmount: number
  qty: number
  restock: boolean
}

/** Net unit amount for a sale/purchase line (decimal-safe display math). */
export function lineUnitAmount(line: AppRecord): number {
  const qty = Number(line.quantity || 0)
  if (qty <= 0) return 0
  if (line.total != null && Number.isFinite(Number(line.total))) {
    return roundMoney(Number(line.total) / qty)
  }
  const price = Number(line.price || line.unitCost || 0)
  return roundMoney(price)
}

export function documentLines(doc: AppRecord | null | undefined): AppRecord[] {
  if (!doc || !Array.isArray(doc.items)) return []
  return doc.items as AppRecord[]
}

export function buildReturnLines(doc: AppRecord | null | undefined, kind: ReturnDocumentKind): ReturnLineDraft[] {
  return documentLines(doc).map((line) => {
    const soldQty = Number(line.quantity || 0)
    const returnedQty = Number(line.returnedQuantity || 0)
    const returnableQty = Math.max(0, roundMoney(soldQty - returnedQty))
    return {
      lineId: String(line.id || ''),
      productId: String(line.productId || ''),
      name: String(line.name || ''),
      soldQty,
      returnedQty,
      returnableQty,
      unitAmount: lineUnitAmount(line),
      qty: 0,
      restock: kind === 'sale',
    }
  }).filter(line => line.returnableQty > 0 && line.lineId)
}

/**
 * Build Purchase Edit line drafts from an original purchase document: every
 * line with its original quantity and unit cost so the purchase can be edited
 * and re-saved via PATCH.
 */
export function buildPurchaseEditLines(
  doc: AppRecord | null | undefined,
  productById: Map<string, AppRecord> = new Map(),
): PurchaseReturnLineDraft[] {
  return documentLines(doc).map((line) => {
    const product = productById.get(String(line.productId || '')) || null
    const qty = roundMoney(Number(line.quantity || 0))
    const cost = Number(line.price || line.unitCost || 0)
    return {
      lineId: String(line.id || ''),
      name: String(line.name || product?.name || ''),
      productId: String(line.productId || ''),
      quantity: qty,
      unitAmount: cost,
      returnableQuantity: qty,
      amount: roundMoney(qty * cost),
      height: line.height == null ? null : Number(line.height),
      width: line.width == null ? null : Number(line.width),
      areaM2: line.areaM2 == null ? null : Number(line.areaM2),
    }
  }).filter(line => line.lineId && line.productId)
}

export function documentHasReturnableLines(doc: AppRecord | null | undefined): boolean {
  return buildReturnLines(doc, 'sale').length > 0
}

/** One fixed original purchase line for Purchase Return mode. */
export type PurchaseReturnLineDraft = {
  lineId: string
  name: string
  productId: string
  quantity: number
  unitAmount: number
  returnableQuantity: number
  amount: number
  /** Sold-by-area purchase line dimensions (metres), when present. */
  height?: number | null
  width?: number | null
  areaM2?: number | null
}

/**
 * Build Purchase Return line drafts from an original purchase document:
 * only lines that still have a returnable quantity, carrying the original
 * unit cost. Quantity defaults to the full returnable amount (the user may
 * reduce it before submitting).
 */
export function buildPurchaseReturnLines(
  doc: AppRecord | null | undefined,
  productById: Map<string, AppRecord> = new Map(),
): PurchaseReturnLineDraft[] {
  return documentLines(doc)
    .filter(line => Number(line.returnableQuantity || 0) > 0)
    .map((line) => {
      const product = productById.get(String(line.productId || '')) || null
      const qty = roundMoney(Number(line.returnableQuantity || 0))
      const cost = Number(line.price || line.unitCost || 0)
      return {
        lineId: String(line.id || ''),
        name: String(line.name || product?.name || ''),
        productId: String(line.productId || ''),
        quantity: qty,
        unitAmount: cost,
        returnableQuantity: qty,
        amount: roundMoney(qty * cost),
        height: line.height == null ? null : Number(line.height),
        width: line.width == null ? null : Number(line.width),
        areaM2: line.areaM2 == null ? null : Number(line.areaM2),
      }
    })
    .filter(line => line.lineId)
}
