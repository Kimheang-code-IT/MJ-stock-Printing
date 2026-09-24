<script setup lang="ts">
import { PAYMENT_METHODS } from '~/config/pos-options'
import type { ModuleTable } from '~/config/modules'
import type { AppRecord } from '~/config/admin-seed'
import { useAppHeader } from '~/composables/layout/useAppHeader'
import { usePosCommands } from '~/repositories/index'
import type {
  DocumentFieldSchema,
  DocumentTabSchema,
} from '~/types/mj/common'
import { multiplyDecimalSafe } from '~/utils/stock/numbers'
import { checkoutPaidNow } from '~/utils/pos/checkout'
import { buildPurchaseEditLines, buildPurchaseReturnLines } from '~/utils/reports/returns'
import { apiErrorMessage, apiFieldErrors, camelCaseFieldKey, isApiErrorHandled, registerInlineFieldErrorConsumer } from '~/utils/api/errors'

/**
 * New Purchase (Stock In = purchase, spec §2.1.x) — built on the same
 * reusable document components as the Stock product document:
 * DocumentAppDocumentPage + schema-driven AppDocumentForm sections + the
 * generic TableAppLineTable (per-line `lines` table with the shared
 *  subtotal/tax/total + paid/outstanding footer). Saving posts ONE
 * /stock/in document — supplier debt for the unpaid balance, the payment row,
 * stock movements, the document number and the audit entry all happen in that
 * single backend transaction.
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
  tax: undefined,
  paidNow: undefined,
  // Return mode read-only header + reason.
  purchaseNo: '',
  supplierName: '',
  returnReason: '',
  lines: [] as Array<Record<string, unknown>>,
})

/* ------------------------------ return mode ------------------------------ */
/** Purchase Return mode: the original purchase is preloaded and Submit records
 *  an immutable Purchase Return (never a new purchase, never an edit). */
const returnMode = ref(false)
const returnPurchaseId = ref('')
const returnLoading = ref(false)
const returnReason = ref('')

/* ------------------------------- edit mode ------------------------------- */
/** Purchase Edit mode: the original Stock In is preloaded and Submit re-saves
 *  it via PATCH (reverse + reapply on the backend). */
const editMode = ref(false)
const editPurchaseId = ref('')

/** View-only: Purchase Report Purchase No → detail form, no edits. */
const viewMode = ref(false)

/** Inline per-field validation messages (shown on the field, never a toast). */
const fieldErrors = reactive<Record<string, string>>({})
function clearFieldErrors() {
  for (const key of Object.keys(fieldErrors)) Reflect.deleteProperty(fieldErrors, key)
}
function clearFieldError(key: string) {
  if (fieldErrors[key]) Reflect.deleteProperty(fieldErrors, key)
}

/** Map backend field_errors (snake_case / line keys) onto form field keys. */
const API_ERROR_FIELD_MAP: Record<string, string> = {
  items: 'lines',
  lines: 'lines',
  product_id: 'lines',
  quantity: 'lines',
  unit_cost: 'lines',
  supplier_id: 'supplierId',
  supplierId: 'supplierId',
  exchange_rate: 'exchangeRate',
  exchangeRate: 'exchangeRate',
}
function applyApiFieldErrors(error: unknown) {
  for (const [key, message] of Object.entries(apiFieldErrors(error))) {
    const mapped = API_ERROR_FIELD_MAP[key] || camelCaseFieldKey(key)
    if (!fieldErrors[mapped]) fieldErrors[mapped] = message
  }
}
// While this form is mounted, useApi routes validation errors here (inline).
const releaseInlineFieldErrors = registerInlineFieldErrorConsumer()
onBeforeUnmount(releaseInlineFieldErrors)

function fieldValue(key: string): unknown {
  // Computed document totals consumed by the line-table footer.
  if (key === 'subtotal') return subtotal.value
  if (key === 'total') return total.value
  if (key === 'paidNow') return paidNow.value
  if (key === 'remaining') return remaining.value
  if (key === 'returnReason') return returnReason.value
  return model[key]
}

function setFieldValue(key: string, value: unknown): void {
  if (viewMode.value) return
  clearFieldError(key)
  if (key === 'returnReason') {
    returnReason.value = String(value ?? '')
    return
  }
  model[key] = value
}

// ---------------------------------------------------------------- masters

onMounted(async () => {
  const returnId = String(route.query.returnPurchaseId || '')
  if (returnId) {
    await loadReturnPurchase(returnId, String(route.query.purchaseNo || ''))
    return
  }
  const viewId = String(route.query.viewPurchaseId || '')
  if (viewId) {
    await loadViewPurchase(viewId, String(route.query.purchaseNo || ''))
    return
  }
  const editId = String(route.query.editPurchaseId || '')
  if (editId) {
    await loadEditPurchase(editId, String(route.query.purchaseNo || ''))
    return
  }
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
    applyDefaultSupplier(productFor(preselect))
  }
})

/** Load an original purchase into the form as a return: preload supplier,
 *  lines and unit cost; Submit records a Purchase Return. */
async function loadReturnPurchase(purchaseId: string, purchaseNo: string) {
  returnLoading.value = true
  try {
    await Promise.all([store.fetchList('products'), store.fetchList('suppliers')])
    await store.fetchList('stockIns', { q: purchaseNo || undefined, limit: 500 })
    const docs = store.list('stockIns') as AppRecord[]
    const doc = docs.find(row => String(row.id) === purchaseId)
    if (!doc) {
      toast.add({ title: t('app.purchase.returnLoadFailed'), color: 'error' })
      await navigateTo('/reports/purchases')
      return
    }
    model.supplierId = String(doc.supplierId || '')
    model.supplierName = String(doc.supplier || '')
    model.purchaseNo = String(doc.purchaseNo || purchaseNo || '')
    model.currency = String(doc.currency || 'USD') === 'KHR' ? 'KHR' : 'USD'
    model.exchangeRate = Number(doc.exchangeRate || 1)
    model.transactionDate = String(doc.date || '').slice(0, 10)
    const productById = new Map(store.list('products').map(row => [String(row.id), row]))
    const returnLines = buildPurchaseReturnLines(doc, productById)
    if (!returnLines.length) {
      toast.add({ title: t('app.reports.nothingToReturn'), color: 'warning' })
      await navigateTo('/reports/purchases')
      return
    }
    model.lines = returnLines
    returnMode.value = true
    returnPurchaseId.value = purchaseId
    returnReason.value = ''
    setTitle(t('app.purchase.returnMode'))
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.purchase.returnLoadFailed'),
        description: apiErrorMessage(error, t('app.purchase.returnLoadFailed')),
        color: 'error',
      })
    }
  }
  finally {
    returnLoading.value = false
  }
}

/** Load an original purchase into the form for editing (all lines, original
 *  quantities/costs); Submit re-saves via PATCH (reverse + reapply). */
async function loadEditPurchase(purchaseId: string, purchaseNo: string) {
  returnLoading.value = true
  try {
    await Promise.all([store.fetchList('products'), store.fetchList('suppliers')])
    await store.fetchList('stockIns', { q: purchaseNo || undefined, limit: 500 })
    const docs = store.list('stockIns') as AppRecord[]
    const doc = docs.find(row => String(row.id) === purchaseId)
    if (!doc) {
      toast.add({ title: t('app.purchase.updateLoadFailed'), color: 'error' })
      await navigateTo('/reports/purchases')
      return
    }
    model.supplierId = String(doc.supplierId || '')
    model.supplierName = String(doc.supplier || '')
    model.purchaseNo = String(doc.purchaseNo || purchaseNo || '')
    model.currency = String(doc.currency || 'USD') === 'KHR' ? 'KHR' : 'USD'
    model.exchangeRate = Number(doc.exchangeRate || 1)
    model.transactionDate = String(doc.date || '').slice(0, 10)
    model.note = String(doc.note || '')
    model.tax = Number(doc.tax ?? doc.taxAmount ?? 0) || undefined
    model.paymentMethod = String(doc.paymentMethodLabel || doc.paymentMethod || 'Cash') || 'Cash'
    model.paidNow = Number(doc.paidAmount ?? 0)
    const productById = new Map(store.list('products').map(row => [String(row.id), row]))
    const editLines = buildPurchaseEditLines(doc, productById)
    if (!editLines.length) {
      toast.add({ title: t('app.purchase.updateLoadFailed'), color: 'warning' })
      await navigateTo('/reports/purchases')
      return
    }
    model.lines = editLines
    editMode.value = true
    editPurchaseId.value = purchaseId
    setTitle(t('app.purchase.editTitle'))
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.purchase.updateLoadFailed'),
        description: apiErrorMessage(error, t('app.purchase.updateLoadFailed')),
        color: 'error',
      })
    }
  }
  finally {
    returnLoading.value = false
  }
}

/** Load a purchase for view-only detail (Purchase Report Purchase No). */
async function loadViewPurchase(purchaseId: string, purchaseNo: string) {
  await loadEditPurchase(purchaseId, purchaseNo)
  if (!editMode.value) return
  editMode.value = false
  viewMode.value = true
  setTitle(t('app.purchase.viewTitle'))
}

/** View-only purchase → edit mode, reusing the already-loaded lines/costs. */
function editFromView() {
  if (!viewMode.value) return
  viewMode.value = false
  editMode.value = true
  setTitle(t('app.purchase.editTitle'))
}

function blankLine(): Record<string, unknown> {
  return { productId: '', height: 0, width: 0, areaM2: 0, quantity: 0, unitAmount: 0, amount: 0 }
}

const supplierOptions = computed(() => store.list('suppliers').map(row => ({
  label: String(row.name || ''),
  value: String(row.id),
})))

function productFor(productId: string) {
  return store.list('products').find(row => String(row.id) === productId) || null
}

/** Default supplier fast-path: the selected product's own supplier prefills
 *  the purchase header. A manual supplier choice is never overwritten. */
const autoSupplierId = ref('')

function applyDefaultSupplier(product: Record<string, unknown> | null) {
  const productSupplier = String(product?.supplierId || '')
  if (!productSupplier) return
  const current = String(model.supplierId || '')
  if (current && current !== autoSupplierId.value) return
  model.supplierId = productSupplier
  autoSupplierId.value = productSupplier
}

/** Products not already on ANOTHER line (one line per product; the backend
 *  rejects duplicates on the same stock-in document). The picker shows the
 *  product NAME only and searches it.
 *  The row's own product stays in the list so its name still resolves — the
 *  table passes a copy of the row, so identity checks would drop it. */
function availableProductOptions(row: Record<string, unknown>) {
  const currentId = String(row.productId || '')
  const lines = Array.isArray(model.lines) ? model.lines as Array<Record<string, unknown>> : []
  const usedByOthers = new Set(lines
    .map(other => String(other.productId || ''))
    .filter(id => id && id !== currentId))
  return store.list('products')
    .filter(product => !usedByOthers.has(String(product.id)))
    .map(product => ({ label: String(product.name || ''), value: String(product.id) }))
}

/** Product cost price per unit (used to prefill an empty line cost). */
function suggestedCost(productId: string): number {
  const product = productFor(productId)
  if (!product) return 0
  const suggested = Number(product.costPrice || 0)
  return suggested > 0 ? suggested : 0
}

// Keep rows coherent: prefill the suggested cost when the line cost is empty
// and the product name, plus the supplier fast-path (the generic line table
// cannot derive cross-column defaults itself).
watch(() => model.lines, (rows) => {
  if (viewMode.value || returnMode.value) return
  if (!Array.isArray(rows)) return
  const next = (rows as Array<Record<string, unknown>>).map((row) => {
    const product = productFor(String(row.productId || ''))
    if (!product) return row
    const unitAmount = Number(row.unitAmount || 0)
    const nextCost = unitAmount > 0 ? unitAmount : suggestedCost(String(row.productId))
    const nextRow: Record<string, unknown> = { ...row, unitAmount: nextCost, name: String(product.name || '') }

    // Prefill supplier from the product when the header is still empty / auto.
    applyDefaultSupplier(product)

    if (JSON.stringify(nextRow) !== JSON.stringify(row)) return nextRow
    return row
  })
  if (JSON.stringify(next) !== JSON.stringify(rows)) model.lines = next
}, { deep: true })

// ---------------------------------------------------------------- schema

const linesTable = computed<ModuleTable>(() => {
  // Return / view: lines are fixed (read-only).
  if (returnMode.value || viewMode.value) {
    return {
      key: 'lines',
      title: t('app.purchase.lines'),
      fitWidth: true,
      columns: [
        { key: 'name', label: t('app.pos.product'), type: 'text', computed: true, width: 'min-w-40' },
        { key: 'height', label: t('app.pos.height'), type: 'number', computed: true, width: 'w-20 min-w-20 text-right tabular-nums' },
        { key: 'width', label: t('app.pos.width'), type: 'number', computed: true, width: 'w-20 min-w-20 text-right tabular-nums' },
        { key: 'areaM2', label: t('app.pos.areaM2'), type: 'number', computed: true, width: 'w-14 min-w-14 text-right tabular-nums' },
        { key: 'unitAmount', label: t('app.purchase.unitCost'), type: 'number', computed: true },
        {
          key: 'quantity',
          label: returnMode.value ? t('app.reports.returnQty') : t('app.fields.quantity'),
          type: 'number',
          computed: viewMode.value,
          required: returnMode.value,
          width: 'w-28 min-w-24',
        },
        { key: 'amount', label: t('app.fields.lineTotal'), type: 'number', computed: true },
      ],
    }
  }
  return {
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
    // Sold-by-area purchase: enter Height × Width (metres) and the quantity
    // (m²) fills in automatically; otherwise type the quantity directly.
    { key: 'height', label: t('app.pos.height'), type: 'number', width: 'w-20 min-w-20 text-right tabular-nums' },
    { key: 'width', label: t('app.pos.width'), type: 'number', width: 'w-20 min-w-20 text-right tabular-nums' },
    { key: 'areaM2', label: t('app.pos.areaM2'), type: 'number', computed: true, width: 'w-14 min-w-14 text-right tabular-nums' },
    { key: 'quantity', label: t('app.fields.quantity'), type: 'number', required: true, width: 'w-24 min-w-24 text-right tabular-nums' },
    { key: 'unitAmount', label: t('app.purchase.unitCost'), type: 'number' },
    { key: 'amount', label: t('app.fields.lineTotal'), type: 'number', computed: true },
  ],
  }
})

const tabs = computed<DocumentTabSchema[]>(() => {
  if (returnMode.value) {
    return [
      {
        id: 'general',
        labelKey: 'app.stock.tabGeneral',
        label: t('app.stock.tabGeneral'),
        sections: [
          {
            id: 'purchase-return',
            titleKey: 'app.purchase.returnMode',
            fields: [
              { key: 'purchaseNo', labelKey: 'app.reports.purchaseNo', type: 'text', readOnly: true },
              { key: 'supplierName', labelKey: 'app.nav.suppliers', type: 'text', readOnly: true },
              { key: 'transactionDate', labelKey: 'app.fields.date', type: 'date', readOnly: true },
              { key: 'currency', labelKey: 'app.fields.currency', type: 'text', readOnly: true },
            ],
          },
          {
            id: 'return-reason',
            fields: [
              { key: 'returnReason', labelKey: 'app.reports.returnReason', type: 'textarea', required: true, colSpan: 2 },
            ],
          },
        ],
      },
      {
        id: 'products',
        labelKey: 'app.purchase.lines',
        sections: [
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
                  // Fixed original lines: no add / remove, no payment footer.
                  hideAdd: true,
                  hideRowActions: true,
                },
              },
            ],
          },
        ],
      },
    ]
  }
  if (viewMode.value) {
    return [{
      id: 'general',
      labelKey: 'app.stock.tabGeneral',
      label: t('app.stock.tabGeneral'),
      sections: [
        {
          id: 'purchase',
          titleKey: 'app.purchase.infoSection',
          fields: [
            { key: 'purchaseNo', labelKey: 'app.reports.purchaseNo', type: 'text', readOnly: true },
            { key: 'supplierName', labelKey: 'app.nav.suppliers', type: 'text', readOnly: true },
            { key: 'transactionDate', labelKey: 'app.fields.date', type: 'date', readOnly: true },
            { key: 'paymentMethod', labelKey: 'app.pos.paymentMethod', type: 'text', readOnly: true },
            { key: 'currency', labelKey: 'app.fields.currency', type: 'text', readOnly: true },
            { key: 'note', labelKey: 'app.fields.note', type: 'textarea', colSpan: 2, readOnly: true },
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
                hideAdd: true,
                hideRowActions: true,
                viewOnly: true,
              },
            },
          ],
        },
      ],
    }]
  }
  return [{
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
            // Tax / Paid now are edited inline in the footer.
            editableTotals: true,
            // USD/KHR toggle beside the table title controls the document currency.
            currencyToggle: true,
          },
        },
      ],
    },
  ],
  }]
})

// ---------------------------------------------------------------- totals

type PurchaseRow = Record<string, unknown> & {
  productId: string
  quantity: number
  unitAmount: number
}

const lines = computed<PurchaseRow[]>(() =>
  (Array.isArray(model.lines) ? model.lines as PurchaseRow[] : []))

/** Lines ready to save: product + quantity + cost are all set. */
const completedLines = computed(() => lines.value.filter((row) => {
  if (!row.productId) return false
  if (!(Number(row.quantity) > 0)) return false
  if (Number(row.unitAmount) < 0) return false
  return true
}))

/** Lines with a product, quantity and cost — the running purchase total. */
const pricedLines = computed(() => lines.value.filter((row) => {
  if (!row.productId) return false
  if (!(Number(row.quantity) > 0)) return false
  return Number(row.unitAmount) >= 0
}))

const subtotal = computed(() =>
  round2(pricedLines.value.reduce(
    (sum, row) => sum + round2(multiplyDecimalSafe(Number(row.quantity || 0), Number(row.unitAmount || 0))),
    0,
  )))

const tax = computed(() => round2(Math.max(0, Number(model.tax ?? 0))))
const total = computed(() => round2(Math.max(0, subtotal.value + tax.value)))
/** Untouched Paid now = pay in full (same as POS cash). Credit pays nothing. */
const paidNow = computed(() => checkoutPaidNow(
  model.paidNow as number | undefined,
  total.value,
  String(model.paymentMethod || '') === 'Credit',
))
const remaining = computed(() => round2(Math.max(0, total.value - paidNow.value)))

const canSave = computed(() =>
  returnMode.value
    ? (completedLines.value.length > 0 && Boolean(returnReason.value.trim()))
    : (completedLines.value.length > 0
      && (remaining.value <= 0 || Boolean(model.supplierId))
      && (model.currency !== 'KHR' || Number(model.exchangeRate || 0) > 0)))

/** Human reason Submit stays blocked — shown as a toast when the user clicks. */
/** Validate into the inline error map; returns true when the form is valid. */
function validate(): boolean {
  clearFieldErrors()
  if (returnMode.value) {
    if (!completedLines.value.length) fieldErrors.lines = t('app.purchase.needLines')
    if (!returnReason.value.trim()) fieldErrors.returnReason = t('app.purchase.needReturnReason')
  }
  else {
    if (!pricedLines.value.length || !completedLines.value.length) fieldErrors.lines = t('app.purchase.needLines')
    if (remaining.value > 0 && !model.supplierId) fieldErrors.supplierId = t('app.purchase.needSupplier')
    if (model.currency === 'KHR' && !(Number(model.exchangeRate || 0) > 0)) {
      fieldErrors.exchangeRate = t('app.purchase.needExchangeRate')
    }
  }
  return Object.keys(fieldErrors).length === 0
}

/** Header CTA: Submit for new purchases, Save changes for edits, Confirm for returns. */
const purchaseSaveLabel = computed(() => {
  if (returnMode.value) return t('app.reports.confirmReturn')
  if (editMode.value) return t('core.common.save')
  return t('core.confirm.submit')
})

// ---------------------------------------------------------------- submit

const saving = ref(false)

async function saveReturn() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    await posCommands.returnPurchase({
      stockInId: returnPurchaseId.value,
      reason: returnReason.value.trim(),
      lines: completedLines.value.map(row => ({
        lineId: String((row as { lineId?: string }).lineId || ''),
        quantity: Number(row.quantity),
      })),
    })
    toast.add({ title: t('app.reports.returnSaved'), color: 'success' })
    void store.fetchList('products')
    void store.fetchList('stockIns')
    await navigateTo('/reports/purchases')
  }
  catch (error: unknown) {
    applyApiFieldErrors(error)
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.reports.returnFailed'),
        description: apiErrorMessage(error, t('app.reports.returnFailed')),
        color: 'error',
      })
    }
  }
  finally {
    saving.value = false
  }
}

/** Save the edited purchase (reverse + reapply on the backend). */
async function saveEdit() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    await posCommands.updatePurchase({
      stockInId: editPurchaseId.value,
      lines: completedLines.value.map(row => ({
        productId: row.productId,
        quantity: Number(row.quantity),
        unitCost: Number(row.unitAmount),
        ...(Number(row.height) > 0 ? { height: Number(row.height) } : {}),
        ...(Number(row.width) > 0 ? { width: Number(row.width) } : {}),
      })),
      taxAmount: tax.value,
      currency: String(model.currency || 'USD') as 'USD' | 'KHR',
      exchangeRate: Number(model.exchangeRate || 1),
      note: String(model.note || '').trim() || null,
      transactionDate: String(model.transactionDate || '').trim() || null,
    })
    toast.add({ title: t('app.purchase.updated'), color: 'success' })
    void store.fetchList('products')
    void store.fetchList('stockIns')
    await navigateTo('/reports/purchases')
  }
  catch (error: unknown) {
    applyApiFieldErrors(error)
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.purchase.updateFailed'),
        description: apiErrorMessage(error, t('app.purchase.updateFailed')),
        color: 'error',
      })
    }
  }
  finally {
    saving.value = false
  }
}

async function save() {
  if (saving.value) return
  if (!validate()) return
  if (returnMode.value) {
    await saveReturn()
    return
  }
  if (editMode.value) {
    await saveEdit()
    return
  }
  if (!canSave.value) return
  saving.value = true
  try {
    await posCommands.createPurchase({
      lines: completedLines.value.map(row => ({
        productId: row.productId,
        quantity: Number(row.quantity),
        unitCost: Number(row.unitAmount),
        ...(Number(row.height) > 0 ? { height: Number(row.height) } : {}),
        ...(Number(row.width) > 0 ? { width: Number(row.width) } : {}),
      })),
      supplierId: String(model.supplierId || '') || null,
      paidAmount: paidNow.value,
      paymentMethod: String(model.paymentMethod || 'Cash'),
      taxAmount: tax.value,
      currency: String(model.currency || 'USD') as 'USD' | 'KHR',
      exchangeRate: Number(model.exchangeRate || 1),
      transactionDate: String(model.transactionDate || '').trim() || null,
      note: String(model.note || '').trim() || null,
    })
    toast.add({ title: t('app.purchase.created'), color: 'success' })
    void store.fetchList('products')
    void store.fetchList('stockIns')
    await navigateTo('/reports/purchases')
  }
  catch (error: unknown) {
    applyApiFieldErrors(error)
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.purchase.saveFailed'),
        description: apiErrorMessage(error, t('app.purchase.saveFailed')),
        color: 'error',
      })
    }
  }
  finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
    <div
      v-if="returnMode"
      class="flex items-center gap-2 border-b border-warning/40 bg-warning/10 px-3 py-1.5 text-sm font-medium text-warning"
    >
      <UIcon name="i-lucide-undo-2" class="size-4" />
      <span>{{ t('app.purchase.returnMode') }}</span>
      <span v-if="model.purchaseNo" class="text-muted">· {{ model.purchaseNo }}</span>
    </div>
    <div
      v-if="viewMode"
      class="flex items-center gap-2 border-b border-info/40 bg-info/10 px-3 py-1.5 text-sm font-medium text-info"
    >
      <UIcon name="i-lucide-eye" class="size-4" />
      <span>{{ t('app.purchase.viewMode') }}</span>
      <span v-if="model.purchaseNo" class="text-muted">· {{ model.purchaseNo }}</span>
      <UButton
        class="ms-auto"
        color="primary"
        variant="soft"
        size="xs"
        icon="i-lucide-pencil"
        :label="t('app.reports.edit')"
        @click="editFromView"
      />
    </div>
    <div
      v-if="editMode"
      class="flex items-center gap-2 border-b border-primary/40 bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
    >
      <UIcon name="i-lucide-pencil" class="size-4" />
      <span>{{ t('app.purchase.editMode') }}</span>
      <span v-if="model.purchaseNo" class="text-muted">· {{ model.purchaseNo }}</span>
    </div>
    <DocumentAppDocumentPage
      :tabs="tabs"
      active-tab="general"
      :field-value="fieldValue"
      :set-field-value="setFieldValue"
      :pending="returnLoading"
      :field-errors="fieldErrors"
      :saving="saving"
      :can-save="!viewMode"
      :confirm-save="canSave"
      :save-label="purchaseSaveLabel"
      :read-only="viewMode"
      :is-create="!editMode && !returnMode && !viewMode"
      :show-tabs="false"
      content-wide
      :show-cancel="true"
      list-to="/reports/purchases"
      :can-export="false"
      @save="save()"
    />
  </div>
</template>
