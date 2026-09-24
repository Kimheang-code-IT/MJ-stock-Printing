<script setup lang="ts">
import PosCartPanel from '~/components/pos/PosCartPanel.vue'
import PosCheckoutPanel from '~/components/pos/PosCheckoutPanel.vue'
import PosProductBrowser from '~/components/pos/PosProductBrowser.vue'
import { useAppHeader } from '~/composables/layout/useAppHeader'
import { useCurrencyRateDialog } from '~/composables/common/useCurrencyRateDialog'
import { usePosChrome } from '~/composables/layout/usePosChrome'
import { usePageSeo } from '~/composables/usePageSeo'
import { useDeliveryCommands, usePosCommands, useSettingsRepositories } from '~/repositories/index'
import type { PosCartLine } from '~/utils/pos/cart'
import {
  cartSubtotal,
  lineAreaM2,
  productImageUrl,
  roundMoney,
} from '~/utils/pos/cart'
import {
  checkoutDeliveryFee,
  checkoutDepositTotal,
  checkoutDue,
  checkoutOutstanding,
  checkoutPaidNow,
  checkoutSaleNet,
  type CheckoutDebtRow,
} from '~/utils/pos/checkout'
import { printSaleInvoice, type SaleInvoicePrintInput } from '~/utils/print/invoice'
import { apiErrorMessage, isApiErrorHandled } from '~/utils/api/errors'
import { saleEditCartLines, saleReturnCartLines } from '~/utils/pos/return'
import type { PrintPaperSize } from '~/utils/print/html'

definePageMeta({ titleKey: 'app.nav.pos', permission: 'pos.access' })

/**
 * POS workspace: product card grid + cart, then checkout (customer/summary/payment).
 * Submit auto-prints the bilingual invoice (no invoice dialog).
 */
type PosStep = 'cart' | 'checkout'

const store = useAppDataStore()
const route = useRoute()
const preferences = usePreferencesStore()
const auth = useAuthStore()
const { t, locale } = useI18n()
const { clear } = useAppHeader()
const { hidePosAppHeader, leavePos } = usePosChrome()
const posCommands = usePosCommands()
const deliveryCommands = useDeliveryCommands()
const { appInfo } = useSettingsRepositories()
const toast = useToast()

const shopName = ref('MJ Printing')
/** Letterhead details from System Settings → App Info (used on printed invoices). */
const shopAddress = ref('')
const shopPhone = ref('')
const shopLogoUrl = ref('/logo.png')
const step = ref<PosStep>('cart')
const search = ref('')
const categoryId = ref('')
const cart = ref<PosCartLine[]>([])
const customerId = ref<string | undefined>(undefined)
const customerName = ref('')
/** Read-only customer snapshot (phone/location live on the customer record;
 *  the checkout panel shows the Name selector only). */
const customerPhone = ref('')
const customerLocation = ref('')
const paymentMethod = ref<string>('Cash')
const paidInput = ref<number | undefined>()
const includedDebtIds = ref<string[]>([])
const deliveryPrice = ref(0)
/** Delivery destination captured in the checkout delivery-info dialog;
 *  prefills the post-sale Create Delivery Note (spec §2.1.9). */
const deliveryPhone = ref('')
const deliveryLocation = ref('')
const needsDelivery = ref(false)
const depositInput = ref(0)
const completing = ref(false)
/** Invoice paper size chosen on the payment keypad (A4 / A5). */
const printPaperSize = ref<PrintPaperSize>('A4')
// ONE document currency for the whole sale (cart → checkout → invoice):
// cart line unitPrice is stored in the sale currency; switching the global
// cart currency converts the stored prices exactly once at the entered rate.
const saleCurrency = ref<'USD' | 'KHR'>('USD')
const exchangeRateInput = ref<number | undefined>()
const saleRate = computed(() =>
  saleCurrency.value === 'KHR' ? Math.max(0, Number(exchangeRateInput.value || 0)) : 1)
/** Convert every stored cart price between currencies — once per switch, so
 *  toggling repeatedly never double-converts an amount. */
function convertCartLines(from: 'USD' | 'KHR', to: 'USD' | 'KHR', rate: number) {
  if (from === to || !(Number(rate) > 0)) return
  const factor = to === 'KHR' ? rate : 1 / rate
  cart.value.forEach((line) => {
    line.unitPrice = roundMoney(line.unitPrice * factor)
  })
}
/** Shared toggle logic: switching to KHR asks for the exchange rate through
 *  the shared dialog; cancelling keeps the previous currency. Switching
 *  currency also invalidates debt settling (debts keep their own currency). */
const {
  dialogOpen: exchangeRateDialogOpen,
  toggle: onSaleCurrencyChange,
  confirm: applySaleExchangeRate,
} = useCurrencyRateDialog({
  currency: saleCurrency,
  rate: exchangeRateInput,
  onChanged: () => {
    includedDebtIds.value = []
    depositInput.value = 0
  },
})

/** Global cart currency switch (cart header selector): runs the shared
 *  rate-dialog flow, then converts the stored cart prices once. */
function onSaleCurrencyRequested(value: 'USD' | 'KHR') {
  if (returnMode.value) return
  if (value === saleCurrency.value) return
  const from = saleCurrency.value
  if (value === 'KHR' && saleRate.value <= 0) {
    // No rate yet — the shared dialog collects it; convert on confirm.
    onSaleCurrencyChange('KHR')
    return
  }
  const rate = saleRate.value
  onSaleCurrencyChange(value)
  convertCartLines(from, value, rate)
}

/** Shared rate dialog confirmed: record the rate, switch to KHR, convert. */
function onConfirmSaleRate(rate: number) {
  const parsed = Number(rate)
  if (!Number.isFinite(parsed) || parsed <= 0) return
  applySaleExchangeRate(parsed)
  convertCartLines('USD', 'KHR', parsed)
}
const lastSaleNo = ref('')
const lastSaleId = ref('')

/* ------------------------------ return mode ------------------------------ */
/** POS return mode: the original invoice is loaded and Submit records an
 *  immutable Sale Return against it (never a new sale). */
const returnMode = ref(false)
const returnSaleId = ref('')
const returnInvoiceNo = ref('')
const returnReason = ref('')
const returnRestock = ref(true)
const returnLoading = ref(false)

/* ------------------------------- edit mode ------------------------------- */
/** POS edit mode: an existing invoice is loaded with its original lines and
 *  prices; Submit re-saves it via PATCH (reverse + reapply on the backend). */
const editMode = ref(false)
const editSaleId = ref('')
const editInvoiceNo = ref('')
const editLoading = ref(false)
const editNote = ref('')

/** View-only: Sales Report Sale No → checkout panel, no edits / no submit. */
const viewMode = ref(false)
const viewSaleId = ref('')
const viewInvoiceNo = ref('')

/** Canonical backend tender method → the POS checkout label. */
const SALE_METHOD_TO_UI: Record<string, string> = {
  CASH: 'Cash',
  BANK_QR: 'Card',
  CUSTOMER_DEBT: 'Credit',
}

onBeforeUnmount(() => {
  hidePosAppHeader.value = false
  clear()
})
usePageSeo({ title: () => t('app.pages.pos') })

// POS is a focused workspace: hide the app header on every step (the cart and
// checkout panels own their own Back / Next buttons).
hidePosAppHeader.value = true

onMounted(async () => {
  void store.fetchList('products')
  void store.fetchList('customers')
  void store.fetchList('categories')
  try {
    const info = await appInfo.get()
    const name = String(info.businessName || info.applicationName || '').trim()
    if (name) shopName.value = name
    shopAddress.value = String(info.address || '').trim()
    shopPhone.value = String(info.supportPhone || '').trim()
    shopLogoUrl.value = String(info.branding?.mainLogoUrl || '').trim() || '/logo.png'
  }
  catch {
    // Keep default shop name when settings are unavailable.
  }
  const returnId = String(route.query.returnSaleId || '')
  if (returnId) {
    await loadReturnSale(returnId)
    return
  }
  const viewId = String(route.query.viewSaleId || '')
  if (viewId) {
    await loadViewSale(viewId)
    return
  }
  const editId = String(route.query.editSaleId || '')
  if (editId) await loadEditSale(editId)
})

const canOperate = computed(() =>
  auth.canAccessPage('pos.access'))

const currency = computed(() => preferences.currency)

const categoryOptions = computed(() => [
  { label: t('app.pos.allCategories'), value: '' },
  ...store.list('categories')
    .filter(row => String(row.status || 'Active') !== 'Inactive')
    .map(row => ({ label: String(row.name || ''), value: String(row.id) })),
])

const products = computed(() => {
  const q = search.value.trim().toLowerCase()
  return store.list('products')
    .filter(row => String(row.status || 'Active') !== 'Inactive')
    .filter(row => !categoryId.value || String(row.categoryId) === categoryId.value)
    .filter((row) => {
      if (!q) return true
      return [row.name, row.code]
        .map(value => String(value || '').toLowerCase())
        .some(value => value.includes(q))
    })
})

/** Checkout customer options: label = name (displayed), phone/location ride
 *  on the item so the selector can search and show them (name · phone ·
 *  address) for faster selection. */
const customerOptions = computed(() =>
  store.list('customers')
    .filter(row => String(row.status) === 'Active')
    .map(row => ({
      label: String(row.name || ''),
      value: String(row.id),
      phone: String(row.phone || ''),
      location: String(row.location || row.address || ''),
      /** Marks the seeded system walk-in record (default checkout customer). */
      isWalkIn: row.is_walk_in === true || row.isWalkIn === true,
      description: [row.phone, row.location || row.address]
        .map(part => String(part || '').trim())
        .filter(Boolean)
        .join(' · '),
    })),
)

/** True when the selected checkout customer is the system walk-in record.
 *  Walk-in sales cannot take debt (spec §5.11). */
const isWalkInSelected = computed(() => {
  if (!customerId.value) return false
  const row = store.get('customers', String(customerId.value))
  return row?.is_walk_in === true || row?.isWalkIn === true
})

/** Default the checkout customer to the seeded walk-in record so an anonymous
 *  cash sale shows it selected (the backend already falls back to walk-in). */
function applyDefaultCustomer() {
  if (customerId.value) return
  const walkIn = customerOptions.value.find(option => option.isWalkIn)
  if (!walkIn) return
  customerId.value = walkIn.value
  customerName.value = walkIn.label
}

const openDebts = computed<CheckoutDebtRow[]>(() => {
  if (!customerId.value) return []
  const salesById = Object.fromEntries(
    store.list('sales').map(row => [String(row.id), row]),
  )
  return store.list('customerDebts')
    .filter(row => String(row.customerId) === String(customerId.value))
    .filter(row => Number(row.remainingAmount || 0) > 0)
    .map((row) => {
      const sale = salesById[String(row.saleId)]
      return {
        ...row,
        id: String(row.id),
        date: String(row.date || '').slice(0, 10),
        invoiceNo: String(row.invoiceNo || sale?.invoiceNo || sale?.saleNo || ''),
        paidAmount: Number(row.paidAmount || 0),
        remainingAmount: Number(row.remainingAmount || 0),
        paymentMethod: String(row.paymentMethod || sale?.paymentMethod || '—'),
      }
    })
    .sort((a, b) => b.date.localeCompare(a.date))
})

const selectedDeposit = computed(() => checkoutDepositTotal(
  openDebts.value
    .filter(row => includedDebtIds.value.includes(row.id))
    .map(row => row.remainingAmount),
))
const appliedDeliveryPrice = computed(() =>
  checkoutDeliveryFee(needsDelivery.value, deliveryPrice.value))
// Cart prices and delivery fee are in the sale currency. Deposit / prior-debt
// payment is settled separately and must not inflate this sale's due amount.
const due = computed(() => checkoutDue(
  checkoutSaleNet(cartSubtotal(cart.value), appliedDeliveryPrice.value),
))
const isCredit = computed(() => paymentMethod.value === 'Credit')
/** Untouched Paid now pays the grand total in full — a walk-in cash sale
 *  submits without typing the tender (spec §5.11 walk-in rule). */
const paidAmount = computed(() =>
  checkoutPaidNow(paidInput.value, due.value, isCredit.value))
const outstandingAmount = computed(() => checkoutOutstanding(due.value, paidAmount.value))
// Previous debt (ខ្វះមុន): all open debts of the customer before this sale.
const previousDebtTotal = computed(() => roundMoney(
  openDebts.value.reduce((sum, row) => sum + row.remainingAmount, 0),
))
// Outstanding after this sale = current-sale outstanding + previous debt not
// settled at checkout (depositInput is the amount allocated to old debts).
const totalOutstanding = computed(() => roundMoney(
  outstandingAmount.value + Math.max(0, previousDebtTotal.value - Number(depositInput.value || 0)),
))

const dateLabel = computed(() => {
  const now = new Date()
  return new Intl.DateTimeFormat(locale.value === 'km' ? 'km-KH' : 'en-GB', {
    year: '2-digit',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(now)
})

const cashierName = computed(() => String(auth.user?.name || auth.user?.email || 'Cashier'))

const canCreateDelivery = computed(() =>
  auth.canAccessPage('delivery.create') || auth.canAccessPage('ALL_PAGES'))

/** Add a product to the cart (or bump its quantity), priced from the master
 *  record's current sale price. */
function addProduct(row: Record<string, unknown>) {
  if (returnMode.value) return
  const id = String(row.id)
  const stock = Number(row.quantity || 0)
  if (stock <= 0) {
    toast.add({ title: t('app.pos.outOfStock'), color: 'warning' })
    return
  }
  const existing = cart.value.find(line => line.productId === id)
  if (existing) {
    if (existing.quantity >= existing.availableStock) {
      toast.add({ title: t('app.pos.stockLimit'), color: 'warning' })
      return
    }
    existing.quantity += 1
    return
  }
  // Product master prices are USD; the cart stores prices in the sale currency.
  const usdPrice = Number(row.salePrice || 0)
  const price = saleCurrency.value === 'KHR' ? usdPrice * saleRate.value : usdPrice
  cart.value.push({
    productId: id,
    name: String(row.name || ''),
    imageUrl: productImageUrl(row),
    availableStock: stock,
    unitPrice: roundMoney(price),
    quantity: 1,
  })
}

function changeQty(productId: string, delta: number) {
  const line = cart.value.find(item => item.productId === productId)
  if (!line) return
  const next = Math.max(1, Math.min(line.availableStock, line.quantity + delta))
  line.quantity = next
}

/** Sold-by-area line: when both H and W (metres) are set, quantity = m². */
function updateDimensions(productId: string, height?: number, width?: number) {
  const line = cart.value.find(item => item.productId === productId)
  if (!line) return
  line.height = height
  line.width = width
  const area = lineAreaM2(line)
  line.areaM2 = area ?? undefined
  // Area lines bill by m²; a cleared pair returns to a plain 1-unit count.
  line.quantity = area ?? 1
}

function updatePrice(productId: string, unitPrice: number) {
  const line = cart.value.find(item => item.productId === productId)
  if (!line) return
  line.unitPrice = Math.max(0, roundMoney(unitPrice))
}

function removeLine(productId: string) {
  cart.value = cart.value.filter(line => line.productId !== productId)
}

function clearCart() {
  cart.value = []
  paidInput.value = undefined
  customerId.value = undefined
  customerName.value = ''
  customerPhone.value = ''
  customerLocation.value = ''
  includedDebtIds.value = []
  deliveryPrice.value = 0
  deliveryPhone.value = ''
  deliveryLocation.value = ''
  needsDelivery.value = false
  depositInput.value = 0
  paymentMethod.value = 'Cash'
  step.value = 'cart'
}

async function goNext() {
  if (!cart.value.length) return
  await Promise.all([
    store.fetchList('customers'),
    store.fetchList('customerDebts'),
    store.fetchList('sales'),
  ])
  applyDefaultCustomer()
  step.value = 'checkout'
}

function goBack() {
  if (viewMode.value) {
    void exitViewMode()
    return
  }
  step.value = 'cart'
}

watch(includedDebtIds, () => {
  depositInput.value = selectedDeposit.value
}, { deep: true })

watch(customerId, (id) => {
  includedDebtIds.value = []
  if (!id) {
    customerName.value = ''
    customerPhone.value = ''
    customerLocation.value = ''
    return
  }
  const row = store.get('customers', String(id))
  customerName.value = String(row?.name || '')
  customerPhone.value = String(row?.phone || '')
  customerLocation.value = String(row?.location || row?.address || '')
})

watch(paymentMethod, (method) => {
  if (method === 'Credit') paidInput.value = 0
  else paidInput.value = undefined
})

/** Walk-in customers cannot take debt (spec §5.11): switching to Credit
 *  without a registered customer is blocked with a hint. */
watch(isCredit, (credit) => {
  if (credit && (!customerId.value || isWalkInSelected.value)) {
    toast.add({ title: t('app.pos.creditRequiresCustomer'), color: 'warning' })
    paymentMethod.value = 'Cash'
  }
})

/* ------------------------------ return mode ------------------------------ */

/** Load an original invoice into the POS as a return: preload the returnable
 *  lines (original price, currency/rate, customer) and record
 *  a Sale Return on Submit — never a new sale. */
async function loadReturnSale(saleId: string) {
  returnLoading.value = true
  try {
    await store.fetchList('products')
    const sale = await posCommands.getSale(saleId)
    const productById = new Map(store.list('products').map(row => [String(row.id), row]))
    saleCurrency.value = sale.currency
    exchangeRateInput.value = sale.currency === 'KHR' ? sale.exchangeRate : undefined
    customerId.value = sale.customerId ? String(sale.customerId) : undefined
    customerName.value = sale.customerName
    returnInvoiceNo.value = sale.invoiceNo
    const lines = saleReturnCartLines(sale, productById)
    if (!lines.length) {
      toast.add({ title: t('app.reports.nothingToReturn'), color: 'warning' })
      await navigateTo('/reports/sales')
      return
    }
    cart.value = lines
    returnMode.value = true
    returnSaleId.value = saleId
    returnReason.value = ''
    returnRestock.value = true
    step.value = 'cart'
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.pos.returnLoadFailed'),
        description: apiErrorMessage(error, t('app.pos.returnLoadFailed')),
        color: 'error',
      })
    }
  }
  finally {
    returnLoading.value = false
  }
}

function exitReturnMode() {
  returnMode.value = false
  returnSaleId.value = ''
  returnInvoiceNo.value = ''
  returnReason.value = ''
  returnRestock.value = true
  cart.value = []
  customerId.value = undefined
  customerName.value = ''
  step.value = 'cart'
}

/** Submit the return against the original invoice (immutable Sale Return). */
async function completeReturn() {
  if (!returnSaleId.value || !cart.value.length || completing.value) return
  const reason = returnReason.value.trim()
  if (!reason) {
    toast.add({ title: t('app.reports.returnQtyRequired'), color: 'warning' })
    return
  }
  const lines = cart.value
    .filter(line => line.saleItemId && Number(line.quantity) > 0)
    .map(line => ({
      lineId: String(line.saleItemId),
      quantity: Number(line.quantity),
      restock: returnRestock.value,
    }))
  if (!lines.length) {
    toast.add({ title: t('app.reports.returnQtyRequired'), color: 'warning' })
    return
  }
  completing.value = true
  try {
    const result = await posCommands.returnSale({
      saleId: returnSaleId.value,
      reason,
      lines,
    })
    toast.add({
      title: `${t('app.reports.returnSaved')} · ${String(result.returnNo || '')}`,
      color: 'success',
    })
    void store.fetchList('products')
    void store.fetchList('sales')
    void store.fetchList('stockMovements')
    const invoiceNo = returnInvoiceNo.value
    const saleId = returnSaleId.value
    exitReturnMode()
    await navigateTo(`/reports/sales?q=${encodeURIComponent(invoiceNo || saleId)}`)
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.reports.returnFailed'),
        description: apiErrorMessage(error, t('app.reports.returnFailed')),
        color: 'error',
      })
    }
  }
  finally {
    completing.value = false
  }
}

/* ------------------------------- edit mode ------------------------------- */

/** Load an existing invoice into the POS for editing: original lines, prices,
 *  currency/rate and customer. Submit re-saves via PATCH. */
async function loadEditSale(saleId: string) {
  editLoading.value = true
  try {
    await store.fetchList('products')
    const sale = await posCommands.getSale(saleId)
    const productById = new Map(store.list('products').map(row => [String(row.id), row]))
    saleCurrency.value = sale.currency
    exchangeRateInput.value = sale.currency === 'KHR' ? sale.exchangeRate : undefined
    customerId.value = sale.customerId ? String(sale.customerId) : undefined
    customerName.value = sale.customerName
    editInvoiceNo.value = sale.invoiceNo
    cart.value = saleEditCartLines(sale, productById)
    editNote.value = sale.note || ''
    paymentMethod.value = SALE_METHOD_TO_UI[sale.paymentMethod] || 'Cash'
    deliveryPrice.value = Number(sale.deliveryPrice || 0)
    needsDelivery.value = Number(sale.deliveryPrice || 0) > 0
    // The paymentMethod watcher clears the tender input; set it after the
    // watcher flush so the saved paid amount survives.
    await nextTick()
    paidInput.value = Number(sale.paidAmount || 0) > 0 ? Number(sale.paidAmount) : undefined
    editMode.value = true
    editSaleId.value = saleId
    step.value = 'cart'
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.pos.updateFailed'),
        description: apiErrorMessage(error, t('app.pos.updateFailed')),
        color: 'error',
      })
    }
    await navigateTo('/reports/sales')
  }
  finally {
    editLoading.value = false
  }
}

function exitEditMode() {
  editMode.value = false
  editSaleId.value = ''
  editInvoiceNo.value = ''
  editNote.value = ''
  cart.value = []
  customerId.value = undefined
  customerName.value = ''
  step.value = 'cart'
}

/** Load an invoice into checkout for view-only detail (Sales Report Sale No). */
async function loadViewSale(saleId: string) {
  editLoading.value = true
  try {
    await store.fetchList('products')
    const sale = await posCommands.getSale(saleId)
    const productById = new Map(store.list('products').map(row => [String(row.id), row]))
    saleCurrency.value = sale.currency
    exchangeRateInput.value = sale.currency === 'KHR' ? sale.exchangeRate : undefined
    customerId.value = sale.customerId ? String(sale.customerId) : undefined
    customerName.value = sale.customerName
    viewInvoiceNo.value = sale.invoiceNo
    cart.value = saleEditCartLines(sale, productById)
    editNote.value = sale.note || ''
    paymentMethod.value = SALE_METHOD_TO_UI[sale.paymentMethod] || 'Cash'
    deliveryPrice.value = Number(sale.deliveryPrice || 0)
    needsDelivery.value = Number(sale.deliveryPrice || 0) > 0
    await nextTick()
    paidInput.value = Number(sale.paidAmount || 0) > 0 ? Number(sale.paidAmount) : undefined
    viewMode.value = true
    viewSaleId.value = saleId
    void store.fetchList('customers')
    void store.fetchList('customerDebts')
    step.value = 'checkout'
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.pos.viewLoadFailed'),
        description: apiErrorMessage(error, t('app.pos.viewLoadFailed')),
        color: 'error',
      })
    }
    await navigateTo('/reports/sales')
  }
  finally {
    editLoading.value = false
  }
}

async function exitViewMode() {
  viewMode.value = false
  viewSaleId.value = ''
  viewInvoiceNo.value = ''
  editNote.value = ''
  cart.value = []
  customerId.value = undefined
  customerName.value = ''
  step.value = 'cart'
  await navigateTo('/reports/sales')
}

/** View-only invoice → edit mode, reusing the already-loaded lines/prices. */
function editFromView() {
  if (!viewSaleId.value || !canOperate.value) return
  editMode.value = true
  editSaleId.value = viewSaleId.value
  editInvoiceNo.value = viewInvoiceNo.value
  viewMode.value = false
  viewSaleId.value = ''
  viewInvoiceNo.value = ''
  step.value = 'cart'
}

/** Save the edited invoice (reverse + reapply on the backend). */
async function saveEditSale() {
  if (!editSaleId.value || !cart.value.length || !canOperate.value || completing.value) return
  if (saleCurrency.value === 'KHR' && saleRate.value <= 0) {
    toast.add({ title: t('app.pos.exchangeRateRequired'), color: 'warning' })
    return
  }
  completing.value = true
  try {
    await posCommands.updateSale({
      saleId: editSaleId.value,
      customerId: customerId.value ? String(customerId.value) : null,
      customerName: customerName.value || null,
      items: cart.value.map(line => ({
        productId: line.productId,
        quantity: line.quantity,
        height: line.height,
        width: line.width,
        unitPrice: line.unitPrice,
      })),
      paymentMethod: paymentMethod.value,
      paidAmount: paidAmount.value,
      note: editNote.value || null,
      deliveryPrice: appliedDeliveryPrice.value,
      currency: saleCurrency.value,
      exchangeRate: saleRate.value,
    })
    toast.add({
      title: `${t('app.pos.saleUpdated')} · ${editInvoiceNo.value}`,
      color: 'success',
    })
    void store.fetchList('products')
    void store.fetchList('sales')
    void store.fetchList('customerDebts')
    void store.fetchList('stockMovements')
    const invoice = editInvoiceNo.value
    exitEditMode()
    await navigateTo(`/reports/sales?q=${encodeURIComponent(invoice)}`)
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.pos.updateFailed'),
        description: apiErrorMessage(error, t('app.pos.updateFailed')),
        color: 'error',
      })
    }
  }
  finally {
    completing.value = false
  }
}

/* ------------------------------ Invoice print size ------------------------------ */

/** Paper-size chooser opened after a successful Submit (A4 default). The
 *  invoice always prints in the sale's own currency (KHR sale → KHR). The
 *  parent owns the open state: choosing A4/A5 prints then closes, while
 *  X/Cancel only closes — the sale is already saved and is never re-submitted.
 *  `pendingDelivery` is snapshotted before the checkout reset so the delivery
 *  note is auto-created (no second form) once the sale + print finish. */
const pendingDelivery = ref<{ saleId: string, phone: string, location: string, fee: number } | null>(null)
/** Checkout keypad confirmed: capture the amount paid, then submit the sale. */
function onPaymentConfirm(amount: number) {
  paidInput.value = Number.isFinite(amount) ? amount : undefined
  void completeSale()
}

async function completeSale() {
  if (returnMode.value) {
    await completeReturn()
    return
  }
  if (editMode.value) {
    await saveEditSale()
    return
  }
  if (!cart.value.length || !canOperate.value || completing.value) return
  if (outstandingAmount.value > 0 && !customerId.value) {
    toast.add({ title: t('app.pos.creditRequiresCustomer'), color: 'warning' })
    return
  }
  if (saleCurrency.value === 'KHR' && saleRate.value <= 0) {
    toast.add({ title: t('app.pos.exchangeRateRequired'), color: 'warning' })
    return
  }
  completing.value = true
  try {
    const snapshot = cart.value.map(line => ({ ...line }))
    const sale = await posCommands.completeSale({
      customerId: customerId.value ? String(customerId.value) : null,
      customerName: customerName.value || null,
      items: cart.value.map(line => ({
        productId: line.productId,
        quantity: line.quantity,
        height: line.height,
        width: line.width,
        // Line prices are already stored in the sale currency.
        unitPrice: line.unitPrice,
      })),
      paymentMethod: paymentMethod.value,
      paidAmount: paidAmount.value,
      deliveryPrice: appliedDeliveryPrice.value,
      deposit: depositInput.value,
      includedDebtIds: includedDebtIds.value,
      currency: saleCurrency.value,
      exchangeRate: saleRate.value,
    })
    lastSaleNo.value = String(sale.invoiceNo || sale.saleNo || '')
    lastSaleId.value = String(sale.id || '')
    const shouldAutoCreateDelivery = needsDelivery.value && canCreateDelivery.value
    // Delivery price captured now — the checkout reset below clears it.
    const deliveryFee = appliedDeliveryPrice.value
    // Invoice payload comes from the sale receipt contract
    // (GET /pos/sales/{id}/receipt). Falls back to the
    // cart snapshot if the receipt cannot be read. No invoice.pdf call.
    let printLines: SaleInvoicePrintInput['lines'] = snapshot
    try {
      const receipt = await posCommands.getSaleReceipt(lastSaleId.value)
      printLines = receipt.items.map(item => ({
        name: item.name,
        quantity: item.quantity,
        height: item.height,
        width: item.width,
        areaM2: item.areaM2,
        unitPrice: item.unitPrice,
      }))
    }
    catch {
      // Keep the snapshot lines — printing must not fail because of the receipt.
    }
    const printInput: SaleInvoicePrintInput = {
      shopName: shopName.value,
      invoiceNo: lastSaleNo.value,
      dateLabel: dateLabel.value,
      customerName: customerName.value || String(sale.customer || t('app.pos.walkIn')),
      cashier: cashierName.value,
      // Everything in the print payload is in the sale currency.
      currency: saleCurrency.value,
      lines: printLines,
      deliveryPrice: appliedDeliveryPrice.value,
      previousDebtAmount: previousDebtTotal.value,
      depositAmount: paidAmount.value,
      outstandingAmount: totalOutstanding.value,
      logoUrl: shopLogoUrl.value || undefined,
      businessName: shopName.value,
      businessAddress: shopAddress.value || undefined,
      businessPhone: shopPhone.value || undefined,
      customerAddress: customerLocation.value || undefined,
      customerPhone: customerPhone.value || undefined,
    }
    toast.add({
      title: `${t('app.pos.saleCompleted')} · ${lastSaleNo.value}`,
      color: 'success',
    })
    // Capture the post-sale delivery target before the checkout reset below
    // clears the delivery fields.
    pendingDelivery.value = shouldAutoCreateDelivery
      ? { saleId: lastSaleId.value, phone: deliveryPhone.value, location: deliveryLocation.value, fee: deliveryFee }
      : null
    cart.value = []
    paidInput.value = undefined
    customerId.value = undefined
    customerName.value = ''
    customerPhone.value = ''
    customerLocation.value = ''
    includedDebtIds.value = []
    deliveryPrice.value = 0
    deliveryPhone.value = ''
    deliveryLocation.value = ''
    needsDelivery.value = false
    depositInput.value = 0
    paymentMethod.value = 'Cash'
    saleCurrency.value = 'USD'
    exchangeRateInput.value = undefined
    step.value = 'cart'
    void store.fetchList('products')
    void store.fetchList('sales')
    void store.fetchList('customers')
    void store.fetchList('customerDebts')
    void store.fetchList('stockMovements')
    // Print in the paper size chosen on the payment keypad (A4 / A5), in the
    // sale's own currency — no print dialog. Printing must never fail the sale.
    const delivery = pendingDelivery.value
    pendingDelivery.value = null
    try {
      await printSaleInvoice(printInput, printPaperSize.value)
    }
    catch {
      // ignore — the sale is already saved
    }
    finally {
      lastSaleNo.value = ''
      lastSaleId.value = ''
      if (delivery) {
        // Delivery was toggled on at checkout: create the note automatically
        // (every sold qty, destination + fee) so the cashier never rebuilds it.
        try {
          const note = await deliveryCommands.createDeliveryNoteFromSale(delivery.saleId, {
            deliveryPhone: delivery.phone || null,
            deliveryLocation: delivery.location || null,
            deliveryFee: delivery.fee || null,
          })
          toast.add({
            title: `${t('app.pos.deliveryCreated')} · ${note.deliveryNo ?? ''}`,
            color: 'success',
          })
          void store.fetchList('deliveryNotes')
        }
        catch (error: unknown) {
          if (!isApiErrorHandled(error)) {
            toast.add({
              title: t('app.pos.deliveryCreateFailed'),
              description: apiErrorMessage(error, t('app.pos.deliveryCreateFailed')),
              color: 'error',
            })
          }
        }
      }
    }
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.pos.saleFailed'),
        description: apiErrorMessage(error, t('app.pos.saleFailed')),
        color: 'error',
      })
    }
  }
  finally {
    completing.value = false
  }
}

</script>

<template>
  <div class="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
    <div
      v-if="returnMode"
      class="flex flex-wrap items-center gap-2 border-b border-warning/40 bg-warning/10 px-3 py-1.5 text-sm font-medium text-warning"
    >
      <UIcon name="i-lucide-undo-2" class="size-4" />
      <span>{{ t('app.pos.returnMode') }}</span>
      <span v-if="returnInvoiceNo" class="text-muted">· {{ returnInvoiceNo }}</span>
      <UButton
        class="ms-auto"
        color="neutral"
        variant="ghost"
        size="xs"
        icon="i-lucide-x"
        :label="t('common.cancel')"
        @click="exitReturnMode"
      />
    </div>

    <div
      v-if="viewMode"
      class="flex flex-wrap items-center gap-2 border-b border-info/40 bg-info/10 px-3 py-1.5 text-sm font-medium text-info"
    >
      <UIcon name="i-lucide-eye" class="size-4" />
      <span>{{ t('app.pos.viewMode') }}</span>
      <span v-if="viewInvoiceNo" class="text-muted">· {{ viewInvoiceNo }}</span>
      <UButton
        v-if="canOperate"
        class="ms-auto"
        color="primary"
        variant="soft"
        size="xs"
        icon="i-lucide-pencil"
        :label="t('app.reports.edit')"
        @click="editFromView"
      />
      <UButton
        :class="canOperate ? '' : 'ms-auto'"
        color="neutral"
        variant="ghost"
        size="xs"
        icon="i-lucide-x"
        :label="t('common.close')"
        @click="exitViewMode"
      />
    </div>

    <div
      v-if="editMode"
      class="flex flex-wrap items-center gap-2 border-b border-primary/40 bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
    >
      <UIcon name="i-lucide-pencil" class="size-4" />
      <span>{{ t('app.pos.editMode') }}</span>
      <span v-if="editInvoiceNo" class="text-muted">· {{ editInvoiceNo }}</span>
      <UButton
        class="ms-auto"
        color="neutral"
        variant="ghost"
        size="xs"
        icon="i-lucide-x"
        :label="t('common.cancel')"
        @click="exitEditMode"
      />
    </div>

    <div
      v-if="step === 'cart'"
      class="flex h-full min-h-0 flex-1 flex-col gap-3 overflow-hidden p-3 lg:flex-row"
    >
      <PosProductBrowser
        v-model:search="search"
        v-model:category-id="categoryId"
        :products="products"
        :categories="categoryOptions"
        :currency="currency"
        :disabled="!canOperate || returnMode"
        @add="addProduct"
      />
      <PosCartPanel
        :cart="cart"
        :sale-currency="saleCurrency"
        :disabled="!canOperate"
        :return-mode="returnMode"
        @change-qty="changeQty"
        @update-dimensions="updateDimensions"
        @update-price="updatePrice"
        @update-sale-currency="onSaleCurrencyRequested"
        @remove="removeLine"
        @clear="clearCart"
        @back="leavePos"
        @next="goNext"
      />
    </div>

    <PosCheckoutPanel
      v-else
      v-model:customer-id="customerId"
      v-model:customer-name="customerName"
      v-model:payment-method="paymentMethod"
      v-model:paid-input="paidInput"
      v-model:delivery-price="deliveryPrice"
      v-model:delivery-phone="deliveryPhone"
      v-model:delivery-location="deliveryLocation"
      v-model:needs-delivery="needsDelivery"
      v-model:deposit-input="depositInput"
      v-model:included-debt-ids="includedDebtIds"
      v-model:paper-size="printPaperSize"
      :customer-phone="customerPhone"
      :customer-location="customerLocation"
      :sale-currency="saleCurrency"
      :cart="cart"
      :currency="currency"
      :debts="openDebts"
      :customer-options="customerOptions"
      :can-operate="canOperate && !viewMode"
      :completing="completing"
      :disabled="viewMode || !canOperate"
      :view-mode="viewMode"
      :return-mode="returnMode"
      :return-reason="returnReason"
      :return-restock="returnRestock"
      @update:return-reason="returnReason = $event"
      @update:return-restock="returnRestock = $event"
      @back="goBack"
      @complete="completeSale"
      @pay="onPaymentConfirm"
    />

    <!-- Shared KHR exchange-rate dialog: opened when the cart currency
         switches to KHR without a known rate. -->
    <CommonAppExchangeRateDialog
      v-model:open="exchangeRateDialogOpen"
      @confirm="onConfirmSaleRate"
    />
  </div>
</template>
