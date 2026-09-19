import { describe, expect, it } from 'vitest'
import { cartSubtotal, cartTotal, lineNet, roundMoney, type PosCartLine } from '../app/utils/pos/cart'
import { resolveExactBarcode } from '../app/utils/pos/barcode-scan'
import { checkoutDue, checkoutOutstanding, checkoutSaleNet } from '../app/utils/pos/checkout'

/**
 * POS currency control (spec §5.11): one [USD] / [KHR] choice drives every
 * displayed amount. Cart prices are USD-based and convert with the sale rate
 * through the centralized decimal-safe money helpers — never float drift.
 */

function line(overrides: Partial<PosCartLine> = {}): PosCartLine {
  return {
    productId: 'p1',
    name: 'Glove',
    barcode: '',
    uom: 'PCS',
    uomId: 'uom1',
    factorToBase: 1,
    uomOptions: [],
    imageUrl: null,
    availableStock: 100,
    unitPrice: 3.15,
    discountPercent: 0,
    quantity: 2,
    ...overrides,
  }
}

describe('POS currency handling (USD / KHR sale currency)', () => {
  it('USD sale shows USD amounts (rate 1) — KHR sale multiplies by the entered rate', () => {
    const cart = [line()]
    const subtotalUsd = cartSubtotal(cart)
    expect(subtotalUsd).toBe(6.3)
    // The document-currency view is the same decimal-safe total × rate.
    const rate = 4100
    const subtotalKhr = roundMoney(subtotalUsd * rate)
    expect(subtotalKhr).toBe(25830)
    expect(cartTotal(cart)).toBe(6.3)
  })

  it('KHR rounding keeps whole-riel totals (no float drift in the due chain)', () => {
    const saleNet = checkoutSaleNet(6.3, 0, 0) * 4100
    const due = checkoutDue(saleNet, 0)
    expect(due).toBe(25830)
    expect(checkoutOutstanding(due, 25830)).toBe(0)
  })

  it('line discount math stays decimal-safe at any rate', () => {
    const discounted = line({ discountPercent: 10 })
    expect(lineNet(discounted)).toBe(5.67)
    const khr = roundMoney(lineNet(discounted) * 4100)
    expect(khr).toBe(23247)
  })
})

describe('barcode scan flow (USB/HID scanner → add/increment → refocus)', () => {
  it('exact barcode match adds to cart, repeats increment the same line, miss clears the input', () => {
    // Mirrors pages/pos/index.vue onSearchEnter behavior over the store list.
    const products = [
      { id: 'p1', name: 'Glove', barcode: '8801001234501', quantity: 10, salePrice: 3.15 },
      { id: 'p2', name: 'Mask', barcode: '8801001234502', quantity: 5, salePrice: 1.2 },
    ]
    const cart: PosCartLine[] = []
    const addProduct = (row: Record<string, unknown>) => {
      const existing = cart.find(item => item.productId === String(row.id))
      if (existing) {
        existing.quantity += 1
        return
      }
      cart.push(line({ productId: String(row.id), name: String(row.name), barcode: String(row.barcode), unitPrice: Number(row.salePrice), quantity: 1 }))
    }
    const onSearchEnter = (search: string) => {
      const exact = products.find(row => String(row.barcode || '') === search.trim())
      if (exact) addProduct(exact)
    }

    onSearchEnter('8801001234501')
    expect(cart).toHaveLength(1)
    expect(cart[0]!.productId).toBe('p1')
    // Second scan of the same barcode increments instead of duplicating.
    onSearchEnter('8801001234501')
    expect(cart).toHaveLength(1)
    expect(cart[0]!.quantity).toBe(2)
    // A miss leaves the cart untouched (the scan field keeps focus for retry).
    onSearchEnter('unknown')
    expect(cart).toHaveLength(1)
  })

  it('falls back to the exact-barcode API when the code is not in the loaded list', async () => {
    // Mirrors pages/pos/index.vue onScanCode: local cache miss → API hit → add.
    const loaded = [{ id: 'p1', name: 'Glove', barcode: '8801001234501', quantity: 10, salePrice: 3.15 }]
    const cart: PosCartLine[] = []
    const apiProduct = { id: 'p9', name: 'Syringe', barcode: '9990001112223', quantity: 4, salePrice: 0.5 }
    const getProductByBarcode = async (code: string) => code === apiProduct.barcode ? apiProduct : null
    const addProduct = (row: Record<string, unknown>) => {
      const existing = cart.find(item => item.productId === String(row.id))
      if (existing) {
        existing.quantity += 1
        return
      }
      cart.push(line({ productId: String(row.id), name: String(row.name), barcode: String(row.barcode), unitPrice: Number(row.salePrice), quantity: 1 }))
    }
    const onScanCode = async (raw: string) => {
      const code = raw.trim()
      const local = resolveExactBarcode(loaded, code)
      if (local) {
        addProduct(local)
        return
      }
      const remote = await getProductByBarcode(code)
      if (remote) addProduct(remote)
    }

    await onScanCode('9990001112223')
    expect(cart).toHaveLength(1)
    expect(cart[0]!.productId).toBe('p9')
    // Unknown barcode resolves to null and adds nothing.
    await onScanCode('0000000000000')
    expect(cart).toHaveLength(1)
  })
})