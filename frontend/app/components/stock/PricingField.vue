<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { PaginationState } from '@tanstack/vue-table'
import { CommonAppCurrencyInput, UButton, UInputNumber, USelect } from '#components'
import { h } from 'vue'
import { moduleDocumentRecordKey } from '~/utils/module/document-tabs'
import { useCurrencyRateDialog } from '~/composables/common/useCurrencyRateDialog'
import type { AppRecord } from '~/config/admin-seed'
import type { SalePriceVersionSelection, UomConversion } from '~/utils/stock/uom-conversions'

/**
 * Pricing editor on the product form (spec §2.1.3 / §5.9 Pricing tab). A
 * compact editable table bound to the record's `uomConversions` array and
 * saved with the same Save as the General tab.
 *
 * Columns (exact UI — only these): **No** (1-based, display only),
 * **Original UOM** (active Setup UOM; unique per product; the POS sell
 * unit), **Convert UOM** (read-only, defaults to the product base UOM from
 * General — shown `symbol — name`), **Conversion qty** (`factor_to_base` > 0;
 * the base=base row is locked at 1), **Sale price** (per Original UOM,
 * > 0), **Delete** (pack rows only; the base row stays so the product
 * always keeps one sellable row). No Default-sale column or field — the POS
 * pre-select unit is always the product's base UOM (save-time
 * normalization stores exactly one `isDefaultSale` on the base row). No
 * Cost column, no Sell-on-POS column, no separate Convert UOM tab.
 */
const props = withDefaults(defineProps<{
  modelValue?: unknown
  disabled?: boolean
}>(), {
  modelValue: () => [],
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [UomConversion[]]
}>()

const { t } = useI18n()
const toast = useToast()
const store = useAppDataStore()
const recordAccess = inject(moduleDocumentRecordKey, null)

/** Whole loaded product record for the version rail (id + saved Pricing rows). */
const productRecord = computed(() => (recordAccess?.get('__record') as AppRecord | null) ?? null)

const baseUomId = computed(() => String(recordAccess?.get('uomId') ?? ''))
const baseUomSymbol = computed(() => {
  const base = store.list('uoms').find(uom => String(uom.id) === baseUomId.value)
  return String(base?.symbol || base?.name || '')
})
/** `symbol — name` label of the product base UOM (Convert UOM default). */
const baseUomLabel = computed(() => {
  const base = store.list('uoms').find(uom => String(uom.id) === baseUomId.value)
  if (!base) return '—'
  const symbol = String(base.symbol || base.name || '')
  const name = String(base.name || '')
  return name && name !== symbol ? `${symbol} — ${name}` : symbol
})
/** Base-row sale price lives on the product record (`salePrice`), not only in `uomConversions`. */
const baseSalePrice = computed(() => Number(recordAccess?.get('salePrice') ?? 0))

function setBaseSalePrice(value: number | null | undefined) {
  recordAccess?.set?.('salePrice', Number(value ?? 0))
}

/** Active Setup UOMs only (spec §2.1.3: inactive UOMs never appear here). */
const activeUoms = computed(() => store.list('uoms')
  .filter(uom => String(uom.status || 'Active') === 'Active')
  .map(uom => ({
    label: `${String(uom.symbol || uom.name)} — ${String(uom.name)}`,
    value: String(uom.id),
    symbol: String(uom.symbol || uom.name || ''),
  })))

type PricingRow = UomConversion & Record<string, unknown> & { __key: string, __base: boolean }

const search = ref('')
const pagination = ref<PaginationState>({ pageIndex: 0, pageSize: 50 })

function toRow(raw: Record<string, unknown>, index: number): PricingRow {
  const uomId = String(raw.uomId ?? '')
  return {
    uomId,
    uomSymbol: String(raw.uomSymbol ?? ''),
    convertUomId: String(raw.convertUomId ?? '') || baseUomId.value,
    convertUomSymbol: String(raw.convertUomSymbol ?? ''),
    factorToBase: Number(raw.factorToBase ?? 1),
    salePrice: Number(raw.salePrice ?? 0),
    costPrice: raw.costPrice == null || raw.costPrice === '' ? null : Number(raw.costPrice),
    __key: `row:${index}:${uomId}`,
    __base: uomId === baseUomId.value,
  }
}

const savedRows = computed<PricingRow[]>(() => {
  const list = Array.isArray(props.modelValue) ? props.modelValue as Array<Record<string, unknown>> : []
  return list.map((row, index) => {
    const mapped = toRow(row, index)
    // The base UOM row and the product's sale price are one value: keep them
    // in sync so editing either side updates the other (spec §5.9 Pricing).
    if (mapped.__base) mapped.salePrice = baseSalePrice.value
    return mapped
  })
})

/**
 * Displayed rows. When nothing is saved yet (new product / legacy record),
 * the base=base row is shown as a draft (factor 1, the record's sale price)
 * — it is materialized into `uomConversions` on the first edit, and the
 * save-time normalization keeps it even when untouched.
 */
const draftBaseRow = computed<PricingRow>(() => ({
  uomId: baseUomId.value,
  uomSymbol: baseUomSymbol.value,
  convertUomId: baseUomId.value,
  convertUomSymbol: baseUomSymbol.value,
  factorToBase: 1,
  salePrice: baseSalePrice.value,
  costPrice: null,
  __key: 'draft-base',
  __base: true,
}))

/**
 * Sale-price version selected in the Sale Price History table (shared through
 * the document record). When set, the Pricing table previews that version's
 * UOM prices **read-only**: the backend stores a version's UOM rows as an
 * immutable snapshot with no update endpoint, so editing must go through
 * "Add Version" (never by silently rewriting the product's `uomConversions`).
 */
const versionSelection = computed<SalePriceVersionSelection | null>(() => {
  const raw = recordAccess?.get('__salePriceSelection')
  return raw && typeof raw === 'object' ? raw as SalePriceVersionSelection : null
})
const isVersionPreview = computed(() => versionSelection.value !== null)
// Version snapshots are always read-only; only "Add Version" changes prices.
const previewReadOnly = computed(() => isVersionPreview.value)
const effectiveDisabled = computed(() => props.disabled || previewReadOnly.value)

/**
 * Pricing table display currency. Product master prices are canonical USD;
 * switching to KHR only changes what the table shows/accepts, converting at
 * the entered rate (1 USD = ? KHR) and converting edits back to USD on save.
 */
const currencyOptions = [
  { value: 'USD' as const, symbol: '$', labelKey: 'app.pos.currencyUsd' },
  { value: 'KHR' as const, symbol: '៛', labelKey: 'app.pos.currencyKhr' },
]
const displayCurrency = ref<'USD' | 'KHR'>('USD')
const exchangeRate = ref<number | undefined>()
const {
  dialogOpen: currencyRateDialogOpen,
  toggle: toggleDisplayCurrency,
  confirm: confirmDisplayCurrency,
} = useCurrencyRateDialog({ currency: displayCurrency, rate: exchangeRate })

/** KHR per 1 USD; guarded so a missing rate never mangles a price. */
const conversionRate = computed(() => Number(exchangeRate.value || 0))

/** Canonical USD → display currency (KHR rounded to 2 decimals). */
function toDisplayPrice(usd: number) {
  const value = Number(usd) || 0
  if (displayCurrency.value !== 'KHR') return value
  return conversionRate.value > 0 ? Math.round(value * conversionRate.value * 100) / 100 : value
}

/** Display currency → canonical USD (stored price is always USD). */
function toUsdPrice(amount: number | undefined) {
  const value = Number(amount) || 0
  if (displayCurrency.value !== 'KHR') return value
  return conversionRate.value > 0 ? Math.round((value / conversionRate.value) * 100) / 100 : value
}

const selectionRows = ref<PricingRow[]>([])

watch(versionSelection, (selected) => {
  if (!selected) {
    selectionRows.value = []
    return
  }
  // Older versions store at least one UOM price; fall back to the version-level
  // price when a legacy version has no child rows.
  const uomRows = selected.uomPrices.length
    ? selected.uomPrices
    : [{
        uomId: baseUomId.value,
        uomSymbol: baseUomSymbol.value,
        factorToBase: 1,
        salePrice: selected.salePrice,
        isDefaultSale: true,
      }]
  selectionRows.value = uomRows.map((uom, index) => ({
    uomId: String(uom.uomId),
    uomSymbol: String(uom.uomSymbol || ''),
    convertUomId: baseUomId.value,
    convertUomSymbol: baseUomSymbol.value,
    factorToBase: Number(uom.factorToBase) || 1,
    salePrice: Number(uom.salePrice) || 0,
    costPrice: null,
    __key: `version:${selected.id}:${index}:${String(uom.uomId)}`,
    __base: String(uom.uomId) === baseUomId.value,
  }))
}, { immediate: true })

/** Displayed rows: the selected version preview, else the product's own Pricing rows. */
const rows = computed<PricingRow[]>(() =>
  isVersionPreview.value
    ? selectionRows.value
    : (savedRows.value.length ? savedRows.value : [draftBaseRow.value]))

function clearVersionSelection() {
  recordAccess?.set?.('__salePriceSelection', null)
}

function emitRows(next: PricingRow[]) {
  emit('update:modelValue', next.map(({ __key, __base, ...row }) => ({ ...row })))
}

function updateRow(key: string, patch: Partial<UomConversion>) {
  if (effectiveDisabled.value) return
  emitRows(rows.value.map(row => row.__key === key ? { ...row, ...patch } : row))
}

function removeRow(key: string) {
  // A version's UOM rows are fixed; the base row can never be deleted.
  if (isVersionPreview.value) return
  emitRows(rows.value.filter(row => row.__key !== key))
}

/** UOM options for a row: active UOMs not already used by another row. */
function uomOptionsFor(row: PricingRow) {
  const used = new Set(rows.value.filter(item => item.__key !== row.__key).map(item => item.uomId))
  return activeUoms.value.filter(option => !used.has(option.value))
}

function addRow() {
  // Version UOM rows are fixed — no adding rows to a historical snapshot.
  if (isVersionPreview.value) return
  // Never offer the base UOM (it already has its own row) or a used UOM.
  const free = activeUoms.value.find(option =>
    option.value !== baseUomId.value && !rows.value.some(row => row.uomId === option.value))
  if (!free) {
    toast.add({ title: t('app.stock.convNoUomLeft'), color: 'warning' })
    return
  }
  const conversion: UomConversion = {
    uomId: free.value,
    uomSymbol: free.symbol,
    convertUomId: baseUomId.value,
    convertUomSymbol: baseUomSymbol.value,
    factorToBase: 1,
    salePrice: 0,
    costPrice: null,
  }
  emitRows([...rows.value, { ...conversion, __key: `new:${Date.now()}`, __base: false }])
}

function onUomChange(key: string, uomId: string) {
  if (rows.value.some(row => row.__key !== key && row.uomId === uomId)) {
    toast.add({ title: t('app.stock.convDuplicate'), color: 'error' })
    return
  }
  const option = activeUoms.value.find(item => item.value === uomId)
  updateRow(key, { uomId, uomSymbol: option?.symbol || '' })
}

/** Conversion helper label: `1 box = 12 pcs`. */
function factorLabel(row: PricingRow) {
  return t('app.stock.convFactorLabel', {
    from: row.uomSymbol || '…',
    n: row.factorToBase,
    base: baseUomSymbol.value || '…',
  })
}

const columns = computed<TableColumn<PricingRow>[]>(() => [
  {
    accessorKey: '__no',
    header: t('app.stock.pricingNo'),
    enableSorting: false,
    meta: { class: { td: 'w-10 text-muted tabular-nums', th: 'w-10' } },
    cell: ({ row }) => h('span', String(row.index + 1)),
  },
  {
    accessorKey: 'uomId',
    header: t('app.stock.pricingOriginalUom'),
    enableSorting: false,
    cell: ({ row }) => {
      // Version preview: the UOM set is fixed, so show it as read-only text.
      if (isVersionPreview.value) {
        return h('span', { class: 'text-sm text-highlighted whitespace-nowrap' },
          row.original.uomSymbol || row.original.uomId || baseUomLabel.value)
      }
      return row.original.__base
        ? h('span', { class: 'text-sm text-highlighted whitespace-nowrap' }, baseUomLabel.value)
        : h(USelect, {
            modelValue: row.original.uomId || undefined,
            items: uomOptionsFor(row.original),
            placeholder: t('app.stock.pricingOriginalUom'),
            size: 'xs',
            class: 'w-40',
            disabled: props.disabled,
            'onUpdate:modelValue': (value: string) => onUomChange(row.original.__key, String(value)),
          })
    },
  },
  {
    accessorKey: 'convertUomId',
    header: t('app.stock.pricingConvertUom'),
    enableSorting: false,
    // Read-only: Convert UOM defaults to the product base UOM (General).
    cell: () => h('span', { class: 'text-sm text-muted whitespace-nowrap' }, baseUomLabel.value),
  },
  {
    accessorKey: 'factorToBase',
    header: t('app.stock.pricingQty'),
    enableSorting: false,
    meta: { class: { td: 'whitespace-nowrap', th: 'whitespace-nowrap' } },
    cell: ({ row }) => h('div', { class: 'flex flex-col gap-0.5' }, [
      h(UInputNumber, {
        modelValue: row.original.__base ? 1 : row.original.factorToBase,
        min: 0,
        step: 0.5,
        size: 'xs',
        class: 'w-24 tabular-nums',
        disabled: effectiveDisabled.value || row.original.__base,
        'onUpdate:modelValue': (value: number | null) => updateRow(row.original.__key, { factorToBase: Number(value ?? 0) }),
      }),
      row.original.__base
        ? null
        : h('span', { class: 'text-[10px] text-muted' }, factorLabel(row.original)),
    ]),
  },
  {
    accessorKey: 'salePrice',
    header: t('app.stock.convSale'),
    enableSorting: false,
    meta: { class: { td: 'whitespace-nowrap', th: '' } },
    cell: ({ row }) => h(CommonAppCurrencyInput, {
      modelValue: toDisplayPrice(row.original.salePrice) || undefined,
      currency: displayCurrency.value,
      min: 0,
      step: 0.01,
      size: 'xs',
      class: 'w-28 tabular-nums',
      align: 'right',
      disabled: effectiveDisabled.value,
      'onUpdate:modelValue': (value: number | undefined) => {
        // Entered in the display currency; stored in canonical USD.
        const usd = toUsdPrice(value)
        // The base row's price stays in sync with the product sale price.
        if (row.original.__base) setBaseSalePrice(usd)
        updateRow(row.original.__key, { salePrice: usd })
      },
    }),
  },
  {
    accessorKey: '__actions',
    header: '',
    enableSorting: false,
    meta: { class: { td: 'w-10', th: 'w-10' } },
    // A version's UOM rows are fixed (no delete), so hide the column in preview.
    cell: ({ row }) => isVersionPreview.value
      ? null
      : h(UButton, {
          size: 'xs',
          color: 'error',
          variant: 'ghost',
          icon: 'i-lucide-trash-2',
          // The base UOM row is never deletable: the product must keep at least
          // one sellable Pricing row (spec §2.1.3).
          disabled: props.disabled || row.original.__base,
          ariaLabel: row.original.__base ? undefined : t('app.ui.delete'),
          onClick: () => removeRow(row.original.__key),
        }),
  },
])
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4 xl:flex-row">
    <div class="flex h-[420px] max-h-[60vh] min-h-0 min-w-0 flex-1 flex-col gap-2">
      <!-- Selected sale-price version: an immutable snapshot, shown read-only.
           Use "Add Version" on the version rail to change prices. -->
      <div
        v-if="versionSelection"
        class="flex items-center justify-between gap-2 rounded-sm border border-default bg-elevated px-3 py-1.5 text-xs text-muted"
      >
        <span class="flex min-w-0 items-center gap-1.5 font-medium">
          <UIcon name="i-lucide-history" class="size-3.5 shrink-0" />
          <span class="truncate">
            {{ t('app.stock.priceHistoryPreviewHistory', { version: versionSelection.version }) }}
          </span>
          <span v-if="versionSelection.batchNo" class="shrink-0 text-muted">· {{ versionSelection.batchNo }}</span>
        </span>
        <UButton
          size="xs"
          variant="ghost"
          color="neutral"
          icon="i-lucide-x"
          :label="t('app.stock.priceHistoryPreviewClear')"
          class="shrink-0"
          @click="clearVersionSelection"
        />
      </div>

      <TableAppListTable
        v-model:search="search"
        v-model:pagination="pagination"
        :data="rows"
        :columns="columns"
        :get-row-id="row => String(row.__key)"
        :search-placeholder="t('app.stock.convSearch')"
        :empty-title="t('app.stock.convEmpty')"
        :empty-description="t('app.stock.convEmptyHint')"
        :empty-actions="(disabled || isVersionPreview) ? [] : [{ icon: 'i-lucide-plus', label: t('app.stock.convAddRow'), onClick: addRow }]"
      >
        <template #actions>
          <UFieldGroup size="sm">
            <UButton
              v-for="option in currencyOptions"
              :key="option.value"
              :label="option.symbol"
              :color="displayCurrency === option.value ? 'primary' : 'neutral'"
              :variant="displayCurrency === option.value ? 'soft' : 'outline'"
              :title="t(option.labelKey)"
              :aria-label="t(option.labelKey)"
              :aria-pressed="displayCurrency === option.value"
              @click="toggleDisplayCurrency(option.value)"
            />
          </UFieldGroup>
          <UButton
            v-if="!disabled && !isVersionPreview"
            size="sm"
            icon="i-lucide-plus"
            class="shrink-0"
            :label="t('app.stock.convAddRow')"
            @click="addRow"
          />
        </template>
      </TableAppListTable>
    </div>

    <CommonAppExchangeRateDialog
      v-model:open="currencyRateDialogOpen"
      :initial-rate="exchangeRate"
      @confirm="confirmDisplayCurrency"
    />

    <!-- Sale-price version rail: version + effective date; click to preview. -->
    <StockPriceVersionsRail
      class="max-h-[60vh] xl:h-[420px]"
      :product="productRecord"
    />
  </div>
</template>
