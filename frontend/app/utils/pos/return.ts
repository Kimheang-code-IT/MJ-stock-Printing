import type { AppRecord } from '~/config/admin-seed'
import type { SaleDetail } from '~/repositories/contracts/entities'
import {
  productImageUrl,
  roundMoney,
  type PosCartLine,
} from '~/utils/pos/cart'

/**
 * Build the POS edit-mode cart from an original sale: every sold line with its
 * original price and full quantity so the invoice can be edited
 * (lines/prices/quantities) and re-saved via PATCH.
 */
export function saleEditCartLines(
  sale: SaleDetail,
  productById: Map<string, AppRecord>,
): PosCartLine[] {
  return sale.items.map((item) => {
    const product = productById.get(item.productId) || null
    const quantity = Number(item.quantity || 0)
    return {
      productId: item.productId,
      name: item.name,
      imageUrl: product ? productImageUrl(product) : null,
      // The edit reverses the original line back into stock first, so at least
      // the originally sold quantity is always available to keep.
      availableStock: Number(product?.quantity || 0) + quantity,
      unitPrice: roundMoney(item.unitPrice),
      height: item.height,
      width: item.width,
      areaM2: item.areaM2,
      quantity,
      saleItemId: item.id,
    }
  })
}

/**
 * Build the POS return-mode cart from an original sale: only the lines that
 * still have a returnable quantity, carrying the original price and
 * currency so Submit records a faithful Sale Return.
 */
export function saleReturnCartLines(
  sale: SaleDetail,
  productById: Map<string, AppRecord>,
): PosCartLine[] {
  const lines: PosCartLine[] = []
  for (const item of sale.items) {
    const returnable = roundMoney(Math.max(0, Number(item.quantity || 0) - Number(item.returnedQuantity || 0)))
    if (returnable <= 0) continue
    const product = productById.get(item.productId) || null
    lines.push({
      productId: item.productId,
      name: item.name,
      imageUrl: product ? productImageUrl(product) : null,
      availableStock: returnable,
      unitPrice: roundMoney(item.unitPrice),
      height: item.height,
      width: item.width,
      areaM2: item.areaM2,
      quantity: returnable,
      saleItemId: item.id,
    })
  }
  return lines
}
