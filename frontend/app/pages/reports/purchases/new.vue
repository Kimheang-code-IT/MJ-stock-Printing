<script setup lang="ts">
import { PAYMENT_METHODS } from '~/config/pos-options'
import type { ModuleTable } from '~/config/modules'
import { useAppHeader } from '~/composables/layout/useAppHeader'
import { usePosCommands, useStockQueries } from '~/repositories/index'
import type { ProductBatchRow } from '~/repositories/contracts/entities'
import type {
  DocumentFieldSchema,
  DocumentTabSchema,
} from '~/types/stock-pos/common'
import { conversionForUom, multiplyDecimalSafe } from '~/utils/stock/uom-conversions'

/**
 * New Purchase (Stock In = purchase, spec §2.1.x) — built on the same
 * reusable document components as the Stock product document:
 * DocumentAppDocumentPage + schema-driven AppDocumentForm sections + the
 * generic TableAppLineTable (per-line `lines` table with the shared
 * subtotal/discount/tax/total + paid/outstanding footer). Saving posts ONE
 * /stock/in document — line UOM conversion, supplier debt for the unpaid
 * balance, the payment row, stock movements, the document number and the
 * audit entry all happen in that single backend transaction.
 *
 * Entry points: Purchase Report Create action, and the Stock Products row
 * action "Purchase Stock" (routes here with ?productId= preselected).
 */
definePageMeta({
  titleKey: 'app.pages.purchaseReport',
  permission: 'stock.in',
})

const route = useRoute()
const store = useAppDataStore()
const { t } = useI18n()
const { setTitle, setBreadcrumbs, clear } = useAppHeader()
const posCommands = usePosCommands()
const toast = useToast()

onBeforeUnmount(clear)

setTitle(t('app.purchase.newTitle'))
setBreadcrumbs([
  { label: t('app.pages.purchaseReport'), to: '/reports/purchases' },
  { label: t('app.purchase.newTitle') },
])

function round2(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100
}

// ---------------------------------------------------------------- model

const model = reactive<Record<string, unknown>>({
  supplierId: '',
  transactionDate: '',
  paymentMethod: 'Cash',
  // Document currency: every amount on the purchase is in THIS currency.
  currency: 'USD',
  exchangeRate: undefined,
  note: '',
  discount: undefined,
  tax: undefined,
  paidNow: undefined,
  lines: [] as Array<Record<string, unknown>>,
})

function fieldValue(key: string): unknown {
  // Computed document totals consumed by the line-table footer.
  if (key === 'subtotal') return subtotal.value
  if (key === 'total') return total.value
  if (key === 'remaining') return remaining.value
  return model[key]
}

function setFieldValue(key: string, value: unknown): void {
  model[key] = value
}

// ---------------------------------------------------------------- masters

onMounted(async () => {
  await Promise.all([
    store.fetchList('suppliers'),
    store.fetchList('products'),
  ])
  if (!String(route.query.productId || '') && (model.lines as unknown[]).length === 0) {
    model.lines = [blankLine()]
  }
  if (!model.transactionDate) {
    model.transactionDate = new Date().toISOString().slice(0, 10)
  }
  // Stock In dialog entry: preselect the product to purchase into stock.
  const preselect = String(route.query.productId || '')
  if (preselect) {
    model.lines = [{ ...blankLine(), productId: preselect }]
  }
})

function blankLine(): Record<string, unknown> {
  return { productId: '', uomId: '', quantity: 0, unitAmount: 0, amount: 0, batchNo: '', expiryDate: '' }
}

// ------------------------------------------------------- batch picking

/** Sentinel option in the Batch picker: generates the next batch no (latest
 *  batch + 1, preserving prefix and zero padding). The lot itself is only
 *  created when the purchase is submitted. */
const NEW_BATCH = '__new__'

const stockQueries = useStockQueries()
/** Existing batch lots per product (batch cache; [] while loading). */
const batchCache = ref(new Map<string, ProductBatchRow[]>())

async function ensureBatches(productId: string): Promise<ProductBatchRow[]> {
  const cached = batchCache.value.get(productId)
  if (cached) return cached
  batchCache.value.set(productId, [])
  try {
    const result = await stockQueries.listProductBatches(productId)
    batchCache.value.set(productId, result.items)
    return result.items
  }
  catch {
    return []
  }
}

/** Latest usable lot of the product (newest receipt that is not expired).
 *  This is the Batch No. default after selecting a product. */
function latestBatch(batches: ProductBatchRow[]): ProductBatchRow | null {
  const usable = batches.filter(batch => batch.batchNo && batch.status !== 'Expired')
  if (!usable.length) return null
  return [...usable].sort((a, b) => b.createdDate.localeCompare(a.createdDate))[0] ?? null
}

/** Next batch number: latest batch + 1 — increment the numeric suffix,
 *  preserving the prefix and zero padding (BATCH-001 → BATCH-002), skipping
 *  numbers already taken. No previous batch → BATCH-001. */
function generateBatchNo(batches: ProductBatchRow[]): string {
  const taken = new Set(batches.map(batch => batch.batchNo).filter(Boolean))
  const latest = [...batches]
    .filter(batch => batch.batchNo)
    .sort((a, b) => b.createdDate.localeCompare(a.createdDate))[0]?.batchNo
  if (!latest) return 'BATCH-001'
  const match = latest.match(/^(.*?)(\d+)$/)
  if (!match) return `${latest}-1`
  const prefix = match[1]!
  const width = match[2]!.length
  let candidate = latest
  let seq = Number(match[2])
  do {
    seq += 1
    candidate = `${prefix}${String(seq).padStart(width, '0')}`
  } while (taken.has(candidate))
  return candidate
}

/** Batch picker options of a row: the product's existing lots (stocking into
 *  one preserves its identity/history), the row's generated new batch no
 *  while it is selected, and the "+ New Batch" option. */
function batchOptionsFor(row: Record<string, unknown>): Array<{ label: string, value: string }> {
  const productId = String(row.productId || '')
  const product = productFor(productId)
  if (!product || !tracksBatch(product)) return []
  const items = (batchCache.value.get(productId) || [])
    .filter(batch => batch.batchNo)
    .map(batch => ({ label: batch.batchNo, value: batch.batchNo }))
  const picked = String(row.batchNo || '')
  if (picked && picked !== NEW_BATCH && !items.some(item => item.value === picked)) {
    items.push({ label: picked, value: picked })
  }
  items.push({ label: t('app.purchase.newBatch'), value: NEW_BATCH })
  return items
}

/** After selecting a product: default the Batch No. to its latest lot
 *  (+ expiry). Re-validates against the live row: product unchanged, batch
 *  untouched. */
async function autofillLatestBatch(row: Record<string, unknown>, productId: string) {
  const batches = await ensureBatches(productId)
  if (!(model.lines as Array<Record<string, unknown>>).includes(row)) return
  if (String(row.productId || '') !== productId) return
  if (String(row.batchNo || '')) return
  const product = productFor(productId)
  if (!product || !tracksBatch(product)) return
  const latest = latestBatch(batches)
  if (!latest) return
  row.batchNo = latest.batchNo
  if (latest.expiryDate) row.expiryDate = latest.expiryDate
}

/** "+ New Batch" picked: resolve the generated number once the product's
 *  batches are loaded, then show it as the row's selected batch. */
async function applyNewBatch(row: Record<string, unknown>, productId: string) {
  const batches = await ensureBatches(productId)
  if (!(model.lines as Array<Record<string, unknown>>).includes(row)) return
  if (String(row.productId || '') !== productId) return
  if (String(row.batchNo || '') !== NEW_BATCH) return
  row.batchNo = generateBatchNo(batches)
}

const supplierOptions = computed(() => store.list('suppliers').map(row => ({
  label: String(row.name || ''),
  value: String(row.id),
})))

function productFor(productId: string) {
  return store.list('products').find(row => String(row.id) === productId) || null
}

/** Products not already on another line (one line per product; the backend
 *  rejects duplicates on the same stock-in document). The picker shows the
 *  product NAME only and searches it (barcode/SKU stay out of the dropdown). */
function availableProductOptions(row: Record<string, unknown>) {
  const lines = Array.isArray(model.lines) ? model.lines as Array<Record<string, unknown>> : []
  const excluded = new Set(lines
    .filter(other => other !== row)
    .map(other => String(other.productId || ''))
    .filter(Boolean))
  return store.list('products')
    .filter(row => !excluded.has(String(row.id)))
    .map(row => ({ label: String(row.name || ''), value: String(row.id) }))
}

/** Batch tracking is per product toggle (spec §5.9 Stock Costing). */
function tracksBatch(product: Record<string, unknown> | null): boolean {
  if (!product) return false
  return product.trackBatch === true
    || (product.trackBatch == null && (product.expiryTracking === true || product.expiryTracking === 'true'))
}

function tracksExpiry(product: Record<string, unknown> | null): boolean {
  if (!product) return false
  return product.trackExpiry === true || product.expiryTracking === true
    || (product.trackExpiry == null && product.expiryTracking === true)
}

/** Cost per the selected UOM from the product Pricing rows. */
function suggestedCost(productId: string, uomId: string): number {
  const product = productFor(productId)
  if (!product) return 0
  const conversion = conversionForUom(product, uomId)
  const suggested = conversion?.costPrice != null
    ? conversion.costPrice
    : multiplyDecimalSafe(Number(product.costPrice || 0), conversion?.factorToBase ?? 1)
  return suggested > 0 ? suggested : 0
}

// Keep rows coherent: the row's UOM follows the product's default UOM (no
// visible UOM column, but the conversion still feeds stock-in math) +
// suggested cost when empty + batch/expiry clearing for unbatched products
// (the generic line table cannot derive cross-column defaults itself).
watch(() => model.lines, (rows) => {
  if (!Array.isArray(rows)) return
  const next = (rows as Array<Record<string, unknown>>).map((row, index) => {
    const product = productFor(String(row.productId || ''))
    if (!product) return row
    // Internal UOM: the product's default/base UOM (hidden column, conversion
    // logic preserved — ledger math happens server-side from factorToBase).
    const nextUomId = String(product.uomId || '')
    const unitAmount = Number(row.unitAmount || 0)
    const nextCost = unitAmount > 0 ? unitAmount : suggestedCost(String(row.productId), nextUomId)
    const nextRow: Record<string, unknown> = { ...row, uomId: nextUomId, unitAmount: nextCost }
    // Base qty display: entered qty × factor (display only — ledger math
    // happens server-side from factorToBase).
    nextRow.baseQuantity = multiplyDecimalSafe(Number(row.quantity || 0), conversionForUom(product, nextUomId)?.factorToBase ?? 1)
    // Batch/expiry columns only when the product tracks them.
    if (!tracksBatch(product)) {
      nextRow.batchNo = ''
    }
    if (!tracksExpiry(product)) nextRow.expiryDate = ''
    // Product changed → default the Batch No. to the product's latest lot.
    const prevRow = (rows as Array<Record<string, unknown>>)[index]
    if (String(nextRow.productId || '') !== String(prevRow?.productId || '')) {
      void autofillLatestBatch(nextRow, String(nextRow.productId || ''))
    }
    else if (nextRow.batchNo !== prevRow?.batchNo) {
      const picked = String(nextRow.batchNo || '')
      if (picked === NEW_BATCH) {
        // Generate the next batch number (shown as the selected value).
        void applyNewBatch(nextRow, String(nextRow.productId || ''))
      }
      else if (picked) {
        // Picking an existing lot stamps the row's expiry from that lot.
        const lot = (batchCache.value.get(String(nextRow.productId || '')) || [])
          .find(batch => batch.batchNo === picked)
        if (lot?.expiryDate) nextRow.expiryDate = lot.expiryDate
      }
    }
    if (JSON.stringify(nextRow) !== JSON.stringify(row)) return nextRow
    return row
  })
  if (JSON.stringify(next) !== JSON.stringify(rows)) model.lines = next
}, { deep: true })

// ---------------------------------------------------------------- schema

const linesTable = computed<ModuleTable>(() => ({
  key: 'lines',
  title: t('app.purchase.lines'),
  addLabelKey: 'app.ui.addRow',
  // Stretch to the page width (no horizontal scroll on desktop); the Product
  // column flex-fills the remainder. Narrow screens scroll via the wrapper.
  fitWidth: true,
  columns: [
    {
      key: 'productId',
      label: t('app.pos.product'),
      type: 'select',
      required: true,
      // Searchable by product name; flex-fill = widest column.
      searchable: true,
      width: 'min-w-40',
      optionItems: row => availableProductOptions(row),
    },
    {
      key: 'batchNo',
      label: t('app.stock.batchNo'),
      type: 'select',
      // Select-only: existing lots + "+ New Batch" (auto-generated number).
      searchable: true,
      width: 'w-44 min-w-36',
      optionItems: row => batchOptionsFor(row),
    },
    { key: 'expiryDate', label: t('app.stock.expiryDateCol'), type: 'date', width: 'w-32' },
    { key: 'quantity', label: t('app.fields.quantity'), type: 'number', required: true },
    { key: 'unitAmount', label: t('app.purchase.unitCost'), type: 'number' },
    { key: 'amount', label: t('app.fields.lineTotal'), type: 'number', computed: true },
  ],
}))

const tabs = computed<DocumentTabSchema[]>(() => [{
  id: 'general',
  labelKey: 'app.stock.tabGeneral',
  label: t('app.stock.tabGeneral'),
  sections: [
    {
      id: 'purchase',
      titleKey: 'app.purchase.infoSection',
      fields: [
        {
          key: 'supplierId',
          labelKey: 'app.nav.suppliers',
          label: t('app.nav.suppliers'),
          type: 'select',
          options: supplierOptions.value,
          placeholderKey: 'app.purchase.selectSupplier',
          helpKey: 'app.purchase.supplierOptionalHint',
        } satisfies DocumentFieldSchema,
        { key: 'transactionDate', labelKey: 'app.fields.date', type: 'date' },
        {
          key: 'paymentMethod',
          labelKey: 'app.pos.paymentMethod',
          type: 'select',
          options: PAYMENT_METHODS.map(method => ({ label: method, value: method })),
        },
        // Document currency is picked with the USD/KHR toggle on the price
        // fields (lines table + totals); the rate is required for KHR buys.
        ...(model.currency === 'KHR'
          ? [{
              key: 'exchangeRate',
              labelKey: 'app.pos.exchangeRate',
              type: 'number',
              helpKey: 'app.pos.exchangeRateRequired',
            } satisfies DocumentFieldSchema]
          : []),
        { key: 'note', labelKey: 'app.fields.note', type: 'textarea', colSpan: 2 },
      ],
    },
    {
      id: 'products',
      titleKey: 'app.purchase.lines',
      fields: [
        {
          key: 'lines',
          labelKey: 'app.purchase.lines',
          type: 'line-table',
          colSpan: 2,
          meta: {
            table: linesTable.value,
            showPricingTotals: true,
            includeTax: true,
            showPaidRemaining: true,
            // Discount / Tax / Paid now are edited inline in the footer.
            editableTotals: true,
            // USD/KHR toggle beside the table title controls the document currency.
            currencyToggle: true,
          },
        },
      ],
    },
  ],
}])

// ---------------------------------------------------------------- totals

type PurchaseRow = Record<string, unknown> & {
  productId: string
  uomId: string
  quantity: number
  unitAmount: number
  batchNo?: string
  expiryDate?: string
}

const lines = computed<PurchaseRow[]>(() =>
  (Array.isArray(model.lines) ? model.lines as PurchaseRow[] : []))

/** Lines ready to save: product + quantity + cost are all set, and the
 *  batch/expiry requirements of the row's product are satisfied. A row still
 *  on the "+ New Batch" sentinel (generation in flight) is not ready yet. */
const completedLines = computed(() => lines.value.filter((row) => {
  if (!row.productId) return false
  if (!(Number(row.quantity) > 0)) return false
  if (Number(row.unitAmount) < 0) return false
  const product = productFor(row.productId)
  // Spec: batch no required when the product tracks batches; expiry date
  // required when it tracks expiry (expiry implies batch).
  if (tracksBatch(product) && (!String(row.batchNo ?? '').trim() || String(row.batchNo) === NEW_BATCH)) return false
  if (tracksExpiry(product) && !String(row.expiryDate ?? '').trim()) return false
  return true
}))

const subtotal = computed(() =>
  round2(completedLines.value.reduce(
    (sum, row) => sum + round2(multiplyDecimalSafe(Number(row.quantity || 0), Number(row.unitAmount || 0))),
    0,
  )))

const discount = computed(() => round2(Math.max(0, Number(model.discount ?? 0))))
const tax = computed(() => round2(Math.max(0, Number(model.tax ?? 0))))
const total = computed(() => round2(Math.max(0, subtotal.value - discount.value + tax.value)))
const paidNow = computed(() => round2(Math.min(Math.max(0, Number(model.paidNow ?? 0)), total.value)))
const remaining = computed(() => round2(Math.max(0, total.value - paidNow.value)))

const canSave = computed(() =>
  completedLines.value.length > 0
  && (remaining.value <= 0 || Boolean(model.supplierId))
  && (model.currency !== 'KHR' || Number(model.exchangeRate || 0) > 0))

// ---------------------------------------------------------------- submit

const saving = ref(false)

async function save() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    await posCommands.createPurchase({
      lines: completedLines.value.map((row) => {
        const product = productFor(row.productId)
        const conversion = conversionForUom(product, String(row.uomId || ''))
        return {
          productId: row.productId,
          quantity: Number(row.quantity),
          unitCost: Number(row.unitAmount),
          uomId: String(row.uomId || product?.uomId || '') || undefined,
          uomSymbol: String(conversion?.uomSymbol || product?.uomSymbol || product?.uom || '') || undefined,
          factorToBase: conversion?.factorToBase ?? 1,
          // Batch traceability: receive into the named lot with its expiry —
          // an existing lot is restocked (identity preserved), the generated
          // "+ New Batch" number creates the lot at confirmation only.
          batchNo: String(row.batchNo || '').trim() || null,
          expiryDate: String(row.expiryDate || '').trim() || null,
        }
      }),
      supplierId: String(model.supplierId || '') || null,
      paidAmount: paidNow.value,
      paymentMethod: String(model.paymentMethod || 'Cash'),
      discountAmount: discount.value,
      taxAmount: tax.value,
      currency: String(model.currency || 'USD') as 'USD' | 'KHR',
      exchangeRate: Number(model.exchangeRate || 1),
      note: String(model.note || '').trim() || null,
    })
    toast.add({ title: t('app.purchase.created'), color: 'success' })
    await navigateTo('/reports/purchases')
  }
  catch (error: unknown) {
    toast.add({
      title: t('app.purchase.saveFailed'),
      description: error instanceof Error ? error.message : String(error),
      color: 'error',
    })
  }
  finally {
    saving.value = false
  }
}
</script>

<template>
  <DocumentAppDocumentPage
    :tabs="tabs"
    active-tab="general"
    :field-value="fieldValue"
    :set-field-value="setFieldValue"
    :saving="saving"
    :can-save="canSave"
    :is-create="true"
    :show-tabs="false"
    content-wide
    :show-cancel="true"
    list-to="/reports/purchases"
    :can-export="false"
    @save="save()"
  />
</template>
