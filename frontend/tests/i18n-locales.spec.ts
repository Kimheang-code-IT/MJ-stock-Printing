import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  buildSaleInvoiceHtml,
} from '../app/utils/print/invoice'
import { printPageCss } from '../app/utils/print/html'
import {
  deliveryStatusLabelKey,
  invoiceDeliveryStatusLabelKey,
} from '../app/utils/delivery/notes'
import en from '../i18n/locales/en.json'
import km from '../i18n/locales/km.json'

type Json = Record<string, unknown>

/** Recursively collect leaf (non-object) key paths of a locale JSON. */
function leafKeys(obj: Json, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return value && typeof value === 'object'
      ? leafKeys(value as Json, path)
      : [path]
  })
}

const enKeys = leafKeys(en)
const kmKeys = leafKeys(km)

describe('i18n locale files', () => {
  it('loads both locale files', () => {
    expect(Object.keys(en).length).toBeGreaterThan(0)
    expect(Object.keys(km).length).toBeGreaterThan(0)
  })

  it('every en.json key exists in km.json (parity)', () => {
    const kmSet = new Set(kmKeys)
    const missing = enKeys.filter(key => !kmSet.has(key))
    expect(missing).toEqual([])
  })

  it('every km.json key exists in en.json (parity)', () => {
    const enSet = new Set(enKeys)
    const missing = kmKeys.filter(key => !enSet.has(key))
    expect(missing).toEqual([])
  })

  it('critical navigation keys exist in both locales', () => {
    const keys = [
      'app.nav.dashboard',
      'app.nav.stock',
      'app.nav.pos',
      'app.nav.deliveryNotes',
      'app.nav.setup',
      'app.nav.reports',
      'app.nav.administration',
    ]
    for (const key of keys) {
      expect(enKeys, key).toContain(key)
      expect(kmKeys, key).toContain(key)
    }
  })

  it('stock, POS, delivery, settings and debt keys exist in both locales', () => {
    const keys = [
      'app.stock.tabProducts',
      'app.stock.tabMovements',
      'app.stock.newProduct',
      'app.pos.completeSale',
      'app.pos.paymentMethod',
      'app.pos.paidAmount',
      'app.delivery.deliveryNo',
      'app.delivery.deliverableLines',
      'app.delivery.statusPending',
      'app.delivery.statusDelivered',
      'app.debt.recordPayment',
      'core.settings.telegramNotificationsTitle',
      'core.settings.saleNotifications',
      'core.settings.notificationLanguage',
    ]
    for (const key of keys) {
      expect(enKeys, key).toContain(key)
      expect(kmKeys, key).toContain(key)
    }
  })

  it('Khmer uses the approved business terminology', () => {
    const nav = km.app.nav as Record<string, string>
    const pages = km.app.pages as Record<string, string>
    expect(nav.dashboard).toBe('ផ្ទាំងគ្រប់គ្រង')
    expect(nav.stock).toBe('ស្តុក')
    expect(nav.deliveryNotes).toBe('ការដឹកជញ្ជូន')
    expect(nav.setup).toBe('ការកំណត់ទិន្នន័យ')
    expect(nav.administration).toBe('ការគ្រប់គ្រងប្រព័ន្ធ')
    expect(pages.stockMovements).toBe('ចលនាស្តុក')
  })

  it('locale JSON files are valid UTF-8 without mojibake artifacts', () => {
    for (const file of ['en.json', 'km.json']) {
      const raw = readFileSync(resolve(__dirname, '../i18n/locales', file), 'utf8')
      expect(raw).not.toContain('â€')
      expect(raw).not.toContain('\uFFFD')
    }
  })
})

describe('invoice bilingual labels (A4 + A5 share one template)', () => {
  const input = {
    shopName: 'Demo Shop',
    invoiceNo: 'INV-000020',
    dateLabel: '10/09/26 10:00',
    customerName: 'Walk-in',
    cashier: 'admin',
    currency: 'USD',
    lines: [{ name: 'Glove', quantity: 1, unitPrice: 3.15 }],
    deliveryPrice: 0,
    previousDebtAmount: 0,
    depositAmount: 0,
    outstandingAmount: 3.15,
  }

  it('renders the same bilingual labels on A4 and A5', () => {
    for (const size of ['A4', 'A5'] as const) {
      const html = buildSaleInvoiceHtml(input, size)
      expect(html).toContain('<span>វិក្កយបត្រ</span><span>INVOICE</span>')
      expect(html).toContain('លេខវិក្កយបត្រ / Invoice No')
      expect(html).toContain('កាលបរិច្ឆេទ / Date')
      expect(html).toContain('ឈ្មោះសហគ្រាស ឬអតិថិជន / Enterprise name/Customer')
      expect(html).toContain('លុយ ជាអក្សរ / Amount in words')
      expect(html).toContain('<tr class="head-km">')
      expect(html).toContain('<tr class="head-en">')
      expect(html).toContain('<th>បរិយាយមុខទំនិញ ឬសេវាកម្ម</th>')
      expect(html).toContain('<th>Description of Goods or Services</th>')
      expect(html).toContain('<th class="num center">Height</th>')
      expect(html).toContain('<th class="num center">Width</th>')
      expect(html).toContain('<th class="num center">m</th>')
      expect(html).toContain('<th class="num center">Qty</th>')
      expect(html).toContain('<th class="num center">Price/m²</th>')
      expect(html).toContain('<th class="num">Amount</th>')
      expect(html).toContain('សរុប / Total (USD)')
      expect(html).toContain("Customer&#39;s Signature &amp; Name")
      expect(html).toContain("Seller&#39;s Signature &amp; Name")
    }
  })
})

describe('delivery status i18n label mapping', () => {
  it('maps every delivery status to an existing key in both locales', () => {
    const statuses = ['Pending', 'Preparing', 'Out for Delivery', 'Delivered', 'Failed', 'Returned']
    const enSet = new Set(enKeys)
    const kmSet = new Set(kmKeys)
    for (const status of statuses) {
      const key = deliveryStatusLabelKey(status)
      expect(enSet.has(key), key).toBe(true)
      expect(kmSet.has(key), key).toBe(true)
    }
  })

  it('maps invoice delivery statuses to existing keys in both locales', () => {
    const enSet = new Set(enKeys)
    const kmSet = new Set(kmKeys)
    for (const raw of ['FULLY_DELIVERED', 'PARTIALLY_DELIVERED', 'PENDING', 'unknown']) {
      const key = invoiceDeliveryStatusLabelKey(raw)
      expect(enSet.has(key), key).toBe(true)
      expect(kmSet.has(key), key).toBe(true)
    }
  })
})

describe('print page setup for both paper sizes', () => {
  it('A4 and A5 both define @page rules', () => {
    expect(printPageCss('A4')).toContain('@page { size: A4;')
    expect(printPageCss('A5')).toContain('@page { size: A5;')
  })
})
