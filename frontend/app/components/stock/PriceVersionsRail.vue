<script setup lang="ts">
import type { DropdownMenuItem } from '@nuxt/ui'
import type { AppRecord } from '~/config/admin-seed'
import type { ProductSalePriceRow } from '~/repositories/contracts/entities'
import { useStockQueries } from '~/repositories/index'
import { formatMoney } from '~/utils/format/format-service'
import { apiErrorMessage, isApiErrorHandled } from '~/utils/api/errors'
import { moduleDocumentRecordKey } from '~/utils/module/document-tabs'
import type { SalePriceVersionSelection } from '~/utils/stock/uom-conversions'
import { pricingRowsFor, salePriceVersionSelection } from '~/utils/stock/uom-conversions'

/**
 * Compact sale-price version rail shown to the right of the Pricing table
 * (product detail Pricing tab). Each entry shows only the version + effective
 * date; clicking a version loads its UOM prices into the Pricing table
 * (read-only snapshot). Add / View details / Activate stay in the row menu.
 * Exactly one version per product + batch scope is POS-active; activating
 * deactivates the previous matching scope and copies the default-sale UOM
 * price onto `products.salePrice`. Old sales keep their historical price.
 */
const props = withDefaults(defineProps<{
  product?: AppRecord | null
}>(), {
  product: null,
})

const stockQueries = useStockQueries()
const { t } = useI18n()
const toast = useToast()
const recordAccess = inject(moduleDocumentRecordKey, null)

/**
 * Version currently selected in the rail and loaded into the Pricing table.
 * Shared through the document record so both panels stay in sync; it is UI
 * state only (never POSTed — `adaptProductIn` forwards known keys).
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

const addOpen = ref(false)
const addDate = ref(new Date().toISOString().slice(0, 10))
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
    loadError.value = apiErrorMessage(error, t('api.somethingWentWrong'))
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

function isSelected(row: ProductSalePriceRow) {
  return selectedId.value === String(row.id)
}

/** Load a version into the Pricing table (click again to clear). */
function selectVersion(row: ProductSalePriceRow) {
  if (!recordAccess?.set) return
  if (isSelected(row)) {
    recordAccess.set('__salePriceSelection', null)
    return
  }
  recordAccess.set('__salePriceSelection', salePriceVersionSelection(row))
}

function openDetails(row: ProductSalePriceRow) {
  detailVersion.value = row
  detailsOpen.value = true
}

function menuItems(row: ProductSalePriceRow): DropdownMenuItem[][] {
  return [[
    {
      label: t('app.stock.priceHistoryViewDetails'),
      icon: 'i-lucide-eye',
      onSelect: () => openDetails(row),
    },
    {
      label: t('app.stock.priceHistoryActivate'),
      icon: 'i-lucide-check',
      disabled: row.isActive || busy.value,
      onSelect: () => { void activate(row) },
    },
  ]]
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
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.stock.priceHistoryFailed'),
        description: apiErrorMessage(error, t('app.stock.priceHistoryFailed')),
        color: 'error',
      })
    }
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
    // Activating copies the default-sale price onto the product; mirror it into
    // the form so the Pricing base row and sale price stay in sync.
    const refreshedRow = rows.value.find(item => String(item.id) === String(row.id))
    const activePrice = Number((refreshedRow ?? row).salePrice)
    if (Number.isFinite(activePrice)) recordAccess?.set?.('salePrice', activePrice)
    // Keep the loaded Pricing table in sync when the selected version was activated.
    if (selectedId.value === String(row.id) && recordAccess?.set) {
      const refreshed = rows.value.find(item => String(item.id) === String(row.id))
      if (refreshed) recordAccess.set('__salePriceSelection', salePriceVersionSelection(refreshed))
    }
  }
  catch (error: unknown) {
    if (!isApiErrorHandled(error)) {
      toast.add({
        title: t('app.stock.priceHistoryFailed'),
        description: apiErrorMessage(error, t('app.stock.priceHistoryFailed')),
        color: 'error',
      })
    }
  }
  finally {
    busy.value = false
  }
}

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
  <aside class="flex min-h-0 w-full shrink-0 flex-col rounded-sm border border-default bg-default xl:w-72">
    <header class="flex items-center justify-between gap-2 border-b border-default px-3 py-2">
      <p class="truncate text-sm font-medium text-highlighted">{{ t('app.stock.priceHistory') }}</p>
      <UButton
        size="xs"
        color="primary"
        variant="soft"
        icon="i-lucide-plus"
        :label="t('app.stock.priceHistoryAdd')"
        :disabled="!product?.id"
        @click="openAdd()"
      />
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto p-2">
      <p v-if="loadError" class="px-1 py-2 text-xs text-error">{{ loadError }}</p>
      <div v-else-if="loading" class="flex justify-center py-4">
        <UIcon name="i-lucide-loader-circle" class="size-4 animate-spin text-muted" />
      </div>
      <p v-else-if="!rows.length" class="px-1 py-3 text-xs text-muted">
        {{ t('app.stock.priceHistoryEmpty') }}
      </p>
      <div v-else class="space-y-1">
        <div
          v-for="row in rows"
          :key="row.id"
          class="group flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 transition-colors"
          :class="isSelected(row) ? 'bg-primary/10' : 'hover:bg-elevated'"
          role="button"
          tabindex="0"
          @click="selectVersion(row)"
          @keydown.enter.prevent="selectVersion(row)"
        >
          <span
            class="grid size-6 shrink-0 place-items-center rounded-full text-[10px] font-semibold tabular-nums"
            :class="row.isActive
              ? 'bg-primary/15 text-primary'
              : isSelected(row) ? 'bg-elevated text-highlighted' : 'bg-elevated text-muted'"
          >
            v{{ row.version }}
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-xs font-medium text-highlighted tabular-nums">{{ row.date }}</span>
            <span v-if="row.batchNo" class="block truncate text-[10px] text-muted">{{ row.batchNo }}</span>
          </span>
          <UDropdownMenu :items="menuItems(row)" :content="{ align: 'end' }">
            <UButton
              icon="i-lucide-ellipsis"
              color="neutral"
              variant="ghost"
              size="xs"
              class="shrink-0 opacity-0 group-hover:opacity-100 focus:opacity-100"
              :aria-label="t('app.ui.actions')"
              @click.stop
            />
          </UDropdownMenu>
        </div>
      </div>
    </div>

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
  </aside>
</template>
