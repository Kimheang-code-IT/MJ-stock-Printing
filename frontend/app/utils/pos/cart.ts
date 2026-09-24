import { roundQty } from '~/utils/stock/numbers'

export type PosCartLine = {
  productId: string
  name: string
  imageUrl: string | null
  /** Remaining stock (raw quantity). */
  availableStock: number
  unitPrice: number
  quantity: number
  /** Sold-by-area dimensions in metres (optional, set together). */
  height?: number
  width?: number
  /** Derived area in m² (height × width) when the dimensions are set. */
  areaM2?: number
  /** POS return mode: the original sale-item id this line returns. */
  saleItemId?: string
}

/** Area in m² of a line, or null for a plain count line. */
export function lineAreaM2(line: Pick<PosCartLine, 'height' | 'width'>): number | null {
  const height = Number(line.height || 0)
  const width = Number(line.width || 0)
  if (height > 0 && width > 0) return roundQty(height * width)
  return null
}

export function lineGross(line: PosCartLine): number {
  return roundMoney(line.unitPrice * line.quantity)
}

export function lineNet(line: PosCartLine): number {
  return roundMoney(lineGross(line))
}

export function cartSubtotal(lines: PosCartLine[]): number {
  return roundMoney(lines.reduce((sum, line) => sum + lineGross(line), 0))
}

export function cartTotal(lines: PosCartLine[]): number {
  return roundMoney(lines.reduce((sum, line) => sum + lineNet(line), 0))
}

export function roundMoney(value: number): number {
  return Math.round((Number(value) || 0) * 100) / 100
}

export function productImageUrl(row: Record<string, unknown>): string | null {
  const candidates = [row.imageUrl, row.image, row.photoUrl, row.thumbnailUrl]
  for (const value of candidates) {
    const text = String(value || '').trim()
    if (text) return text
  }
  return null
}
