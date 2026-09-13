<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { PaginationState } from '@tanstack/vue-table'
import { UBadge, UButton } from '#components'
import { h } from 'vue'
import type { AppRecord } from '~/config/admin-seed'
import type { ProductSalePriceRow, SalePriceUomRow } from '~/repositories/contracts/entities'
import { useStockQueries } from '~/repositories/index'
import { formatMoney } from '~/utils/format/format-service'
import { moduleDocumentRecordKey } from '~/utils/module/document-tabs'
import type { SalePriceVersionSelection } from '~/utils/stock/uom-conversions'
import { pricingRowsFor, salePriceVersionSelection } from '~/utils/stock/uom-conversions'

/**
 * Sale-price version history of one product (product detail Pricing tab).
 * One row per version: Version + optional Batch/Lot scope + its UOM prices +
 * effective date + status. Selecting a row loads the version into the Pricing
 * table below for review (POS-active = editable, older = read-only history);
 * "View Details" opens the full pricing breakdown (purchase date/cost when the
 * API reports them). Exactly one version per product + batch scope is
 * POS-active; activating deactivates the previous matching scope and copies
 * the default-sale UOM price onto `products.salePrice`. Old sales keep their
 * stored historical price. Batch expiry/stock logic is untouched.
 */
const props = withDefaults(defineProps<{
  product?: AppRecord | null
  /** Bump to reload after an external change. */
  reloadKey?: number
}>(), {
  product: null,
  reloadKey: 0,
})

const emit = defineEmits<{
  /** Active price changed (parent may refresh the record). */
  changed: []
}>()

const stockQueries = useStockQueries()
const { t } = useI18n()
const toast = useToast()
const recordAccess = inject(moduleDocumentRecordKey, null)

/**
 * Version currently selected in the history table and loaded into the Pricing
 * table below. Shared through the document record so both panels stay in sync;
 * it is UI state only (never POSTed — `adaptProductIn` forwards known keys).
 */
const selection = computed<SalePriceVersionSelection | null>(() => {
  const raw = recordAccess?.get('__salePriceSelection')
  return raw && typeof raw === 'object' ? raw as SalePriceVersionSelection : null
})
const selectedId = computed(() => (selection.value?.id ? String(selection.value.id) : ''))

const detailsOpen = ref(false)
const detailVersion = ref<ProductSalePriceRow | null>(null)

const loading = ref(false)
const busy = ref(false)
const loadError = ref<string | null>(null)
const rows = ref<ProductSalePriceRow[]>([])
const pagination = ref<PaginationState>({ pageIndex: 0, pageSize: 10 })

const addOpen = ref(false)
const addDate = ref(new Date().toISOString().slice(0, 10))
const addPrice = ref<number | undefined>()
const addBatchNo = ref('')
const addPurchaseDate = ref('')
const addExpiryDate = ref('')

/** UOM price rows of the new version, prefilled from the product's Pricing
 *  rows (one row per sellable UOM: pcs / pack / box inside the same version). */
interface UomPriceDraft {
  uomId: string
  uomSymbol: string
  factorToBase: number
  salePrice: number | undefined
  isDefaultSale: boolean
}
const addUomPrices = ref<UomPriceDraft[]>([])

function openAdd() {
  addDate.value = new Date().toISOString().slice(0, 10)
  addPrice.value = undefined
  addBatchNo.value = ''
  addPurchaseDate.value = ''
  addExpiryDate.value = ''
  addUomPrices.value = pricingRowsFor(props.product).map(row => ({
    uomId: row.uomId,
    uomSymbol: String(row.uomSymbol || ''),
    factorToBase: Number(row.factorToBase) || 1,
    salePrice: row.salePrice != null && Number(row.salePrice) > 0 ? Number(row.salePrice) : undefined,
    isDefaultSale: row.isDefaultSale === true,
  }))
  addOpen.value = true
}

async function load() {
  if (!props.product?.id) {
    rows.value = []
    return
  }
  loading.value = true
  loadError.value = null
  try {
    const result = await stockQueries.listSalePrices(String(props.product.id), { limit: 50 })
    rows.value = result.items
  }
  catch (error: unknown) {
    loadError.value = error instanceof Error ? error.message : String(error)
    rows.value = []
  }
  finally {
    loading.value = false
  }
}

watch(() => props.product?.id, () => {
  // A different product invalidates the selected version (avoid touching the
  // record when there is nothing selected — keeps the form untouched on mount).
  if (recordAccess?.get('__salePriceSelection')) {
    recordAccess?.set?.('__salePriceSelection', null)
  }
  void load()
}, { immediate: true })
watch(() => props.reloadKey, () => void load())

/** Load a version into the Pricing table below (click again to clear). */
function selectVersion(row: ProductSalePriceRow) {
  if (!recordAccess?.set) return
  if (selectedId.value === String(row.id)) {
    recordAccess.set('__salePriceSelection', null)
    return
  }
  recordAccess.set('__salePriceSelection', salePriceVersionSelection(row))
}

function onRowSelect(event: Event, row: { original: ProductSalePriceRow }) {
  const target = event.target as HTMLElement | null
  // Clicks on row buttons (Activate / View Details) must not change selection.
  if (target?.closest('a, button, input, [role="menuitem"], [data-slot="dropdown-menu"]')) return
  selectVersion(row.original)
}

function openDetails(row: ProductSalePriceRow) {
  detailVersion.value = row
  detailsOpen.value = true
}

const canAdd = computed(() =>
  Boolean(String(addDate.value || '').trim())
  && addUomPrices.value.length > 0
  && addUomPrices.value.every(row => Number(row.salePrice) > 0))

async function addVersion() {
  if (!canAdd.value || busy.value || !props.product) return
  busy.value = true
  try {
    // Version-level price = the default-sale UOM row's price.
    const defaultPrice = addUomPrices.value.find(row => row.isDefaultSale)
      ?? addUomPrices.value[0]!
    await stockQueries.addSalePrice(String(props.product.id), {
      date: String(addDate.value),
      salePrice: Number(defaultPrice.salePrice),
      batchNo: String(addBatchNo.value || '').trim() || null,
      purchaseDate: String(addPurchaseDate.value || '').trim() || null,
      expiryDate: String(addExpiryDate.value || '').trim() || null,
      uomPrices: addUomPrices.value.map(row => ({
        uomId: row.uomId,
        uomSymbol: row.uomSymbol || null,
        factorToBase: row.factorToBase,
        salePrice: Number(row.salePrice),
        isDefaultSale: row.isDefaultSale,
      })),
    })
    addOpen.value = false
    toast.add({ title: t('app.stock.priceHistoryAdded'), color: 'success' })
    await load()
    emit('changed')
  }
  catch (error: unknown) {
    toast.add({
      title: t('app.stock.priceHistoryFailed'),
      description: error instanceof Error ? error.message : String(error),
      color: 'error',
    })
  }
  finally {
    busy.value = false
  }
}

async function activate(row: ProductSalePriceRow) {
  if (busy.value || row.isActive || !props.product) return
  busy.value = true
  try {
    await stockQueries.activateSalePrice(String(props.product.id), String(row.id))
    toast.add({ title: t('app.stock.priceHistoryActivated'), color: 'success' })
    await load()
    // Keep the loaded Pricing table in sync when the selected version was activated.
    if (selectedId.value === String(row.id) && recordAccess?.set) {
      const refreshed = rows.value.find(item => String(item.id) === String(row.id))
      if (refreshed) recordAccess.set('__salePriceSelection', salePriceVersionSelection(refreshed))
    }
    emit('changed')
  }
  catch (error: unknown) {
    toast.add({
      title: t('app.stock.priceHistoryFailed'),
      description: error instanceof Error ? error.message : String(error),
      color: 'error',
    })
  }
  finally {
    busy.value = false
  }
}

const versionCell = ({ row }: { row: { original: ProductSalePriceRow } }) => {
  const selected = selectedId.value === String(row.original.id)
  return h('div', { class: 'flex items-center gap-1.5' }, [
    h('span', { class: selected ? 'font-semibold text-primary tabular-nums' : 'font-medium tabular-nums' },
      `v${row.original.version}`),
    selected
      ? h(UBadge, { color: 'primary', variant: 'subtle', size: 'sm' }, () => t('app.stock.priceHistorySelected'))
      : null,
  ])
}

const priceCell = ({ row }: { row: { original: ProductSalePriceRow } }) => {
  // Base/default-sale price + the version's other UOM prices underneath.
  const otherPrices = (row.original.uomPrices || [])
    .filter((uomRow: SalePriceUomRow) => !uomRow.isDefaultSale && uomRow.salePrice !== row.original.salePrice)
  return h('div', { class: 'text-end' }, [
    h('span', { class: 'tabular-nums whitespace-nowrap font-medium' }, formatMoney(row.original.salePrice)),
    ...otherPrices.map((uomRow: SalePriceUomRow) => h(
      'span',
      { class: 'block text-[11px] leading-tight text-muted tabular-nums whitespace-nowrap' },
      `${uomRow.uomSymbol || ''} ×${uomRow.factorToBase}: ${formatMoney(uomRow.salePrice)}`,
    )),
  ])
}

const activeCell = ({ row }: { row: { original: ProductSalePriceRow } }) =>
  h(UBadge, {
    color: row.original.isActive ? 'success' : 'neutral',
    variant: 'subtle',
    size: 'sm',
  }, () => row.original.isActive ? t('app.stock.priceHistoryActive') : t('app.stock.priceHistoryInactive'))

const actionCell = ({ row }: { row: { original: ProductSalePriceRow } }) =>
  h('div', { class: 'flex items-center justify-end gap-1' }, [
    h(UButton, {
      size: 'xs',
      variant: 'ghost',
      color: 'neutral',
      icon: 'i-lucide-eye',
      label: t('app.stock.priceHistoryViewDetails'),
      onClick: () => openDetails(row.original),
    }),
    h(UButton, {
      size: 'xs',
      variant: 'soft',
      color: 'primary',
      icon: 'i-lucide-check',
      label: t('app.stock.priceHistoryActivate'),
      disabled: row.original.isActive || busy.value,
      onClick: () => void activate(row.original),
    }),
  ])

const columns = computed<TableColumn<ProductSalePriceRow & Record<string, unknown>>[]>(() => [
  {
    accessorKey: 'version',
    header: t('app.stock.version'),
    enableSorting: false,
    cell: versionCell as never,
  },
  {
    accessorKey: 'batchNo',
    header: t('app.stock.batchNo'),
    enableSorting: false,
    cell: ({ row }) => row.original.batchNo || t('app.stock.priceHistoryAllLots'),
  },
  {
    accessorKey: 'salePrice',
    header: t('app.stock.priceHistoryUomPrices'),
    enableSorting: false,
    cell: priceCell as never,
  },
  {
    accessorKey: 'date',
    header: t('app.stock.priceHistoryEffectiveDate'),
    enableSorting: false,
    meta: { class: { td: 'whitespace-nowrap text-muted', th: '' } },
    cell: ({ row }) => row.original.date,
  },
  {
    accessorKey: 'isActive',
    header: t('app.fields.status'),
    enableSorting: false,
    cell: activeCell as never,
  },
  {
    accessorKey: '__actions',
    header: '',
    enableSorting: false,
    cell: actionCell as never,
  },
])

/** Read-only detail rows of the version in the View Details dialog. */
const detailItems = computed(() => {
  const version = detailVersion.value
  if (!version) return []
  const items: Array<{ label: string, value: string }> = [
    { label: t('app.stock.version'), value: `v${version.version}` },
    { label: t('app.stock.batchNo'), value: version.batchNo || t('app.stock.priceHistoryAllLots') },
  ]
  // Purchase Date / Cost are optional version metadata ("if available").
  if (version.purchaseDate) items.push({ label: t('app.stock.purchaseDate'), value: version.purchaseDate })
  if (version.purchaseCost != null) {
    items.push({ label: t('app.stock.costPrice'), value: formatMoney(version.purchaseCost) })
  }
  items.push({ label: t('app.stock.priceHistoryEffectiveDate'), value: version.date })
  items.push({
    label: t('app.fields.status'),
    value: version.isActive ? t('app.stock.priceHistoryActive') : t('app.stock.priceHistoryInactive'),
  })
  return items
})
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex items-center justify-between gap-2">
      <p class="text-sm font-medium">{{ t('app.stock.priceHistory') }}</p>
      <UButton
        size="xs"
        color="primary"
        variant="soft"
        icon="i-lucide-plus"
        :label="t('app.stock.priceHistoryAdd')"
        :disabled="!product?.id"
        @click="openAdd()"
      />
    </div>

    <p v-if="loadError" class="text-sm text-error">{{ loadError }}</p>
    <TableAppListTable
      v-model:pagination="pagination"
      :data="rows"
      :columns="columns"
      :loading="loading"
      :empty-title="t('app.stock.priceHistoryEmpty')"
      @select="onRowSelect"
    />

    <!-- Add version dialog -->
    <CommonAppDialog
      v-model:open="addOpen"
      :title="t('app.stock.priceHistoryAdd')"
      icon="i-lucide-tag"
      size="sm"
      :loading="busy"
    >
      <div class="space-y-3">
        <p class="text-xs text-muted">{{ t('app.stock.priceHistoryHint') }}</p>
        <div class="grid grid-cols-2 gap-3">
          <CommonAppDateField
            v-model="addDate"
            :label="t('app.fields.date')"
            class="w-full"
          />
          <CommonAppTextField
            v-model="addBatchNo"
            :label="t('app.stock.batchNo')"
            :help="t('app.stock.priceVersionBatchHint')"
            class="w-full"
          />
          <CommonAppDateField
            v-model="addPurchaseDate"
            :label="t('app.stock.purchaseDate')"
            class="w-full"
          />
          <CommonAppDateField
            v-model="addExpiryDate"
            :label="t('app.stock.expiryDateCol')"
            class="w-full"
          />
        </div>

        <!-- UOM price rows inside this version (pcs / pack / box…). -->
        <div class="space-y-1">
          <p class="text-sm font-medium">{{ t('app.stock.priceVersionUomPrices') }}</p>
          <div
            v-for="uomRow in addUomPrices"
            :key="uomRow.uomId"
            class="grid grid-cols-3 items-end gap-2"
          >
            <CommonAppTextField
              :model-value="`${uomRow.uomSymbol || uomRow.uomId} · ×${uomRow.factorToBase}`"
              :label="t('app.pos.uom')"
              :disabled="true"
              class="w-full"
            />
            <CommonAppTextField
              :model-value="String(uomRow.factorToBase)"
              :label="t('app.stock.baseQty')"
              :disabled="true"
              class="w-full"
            />
            <CommonAppMoneyField
              v-model="uomRow.salePrice"
              :label="t('app.stock.salePrice')"
              :required="true"
              class="w-full"
            />
          </div>
        </div>
      </div>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="ghost"
            :label="t('common.cancel')"
            @click="addOpen = false"
          />
          <UButton
            color="primary"
            icon="i-lucide-plus"
            :loading="busy"
            :disabled="!canAdd"
            :label="t('app.stock.priceHistoryAdd')"
            @click="addVersion"
          />
        </div>
      </template>
    </CommonAppDialog>

    <!-- Version pricing details (read-only). -->
    <CommonAppDialog
      v-model:open="detailsOpen"
      :title="t('app.stock.priceHistoryDetailsTitle')"
      icon="i-lucide-tag"
      size="md"
    >
      <div class="space-y-4">
        <div class="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
          <div v-for="item in detailItems" :key="item.label">
            <p class="text-[11px] text-muted">{{ item.label }}</p>
            <p class="font-medium">{{ item.value }}</p>
          </div>
        </div>

        <div class="space-y-1">
          <p class="text-sm font-medium">{{ t('app.stock.priceVersionUomPrices') }}</p>
          <div class="overflow-hidden rounded-sm border border-default">
            <table class="w-full text-sm">
              <thead class="bg-elevated text-xs text-highlighted">
                <tr>
                  <th class="px-3 py-1.5 text-left font-semibold">{{ t('app.pos.uom') }}</th>
                  <th class="px-3 py-1.5 text-right font-semibold">{{ t('app.stock.pricingQty') }}</th>
                  <th class="px-3 py-1.5 text-right font-semibold">{{ t('app.stock.salePrice') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="uomRow in (detailVersion?.uomPrices || [])"
                  :key="uomRow.uomId"
                  class="border-t border-default"
                >
                  <td class="px-3 py-1.5">{{ uomRow.uomSymbol || uomRow.uomId }}</td>
                  <td class="px-3 py-1.5 text-right tabular-nums">{{ uomRow.factorToBase }}</td>
                  <td class="px-3 py-1.5 text-right font-medium tabular-nums">{{ formatMoney(uomRow.salePrice) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="flex w-full justify-end">
          <UButton
            color="neutral"
            variant="ghost"
            :label="t('actions.close')"
            @click="detailsOpen = false"
          />
        </div>
      </template>
    </CommonAppDialog>
  </div>
</template>
