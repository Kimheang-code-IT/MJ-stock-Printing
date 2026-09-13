<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { PaginationState } from '@tanstack/vue-table'
import { UBadge, UButton } from '#components'
import { h } from 'vue'
import type { AppRecord } from '~/config/admin-seed'
import type { ProductSalePriceRow } from '~/repositories/contracts/entities'
import { useStockQueries } from '~/repositories/index'
import { formatMoney } from '~/utils/format/format-service'

/**
 * Sale-price version history of one product (product detail Pricing tab).
 * Versions are POS sale prices by **Product + UOM = base** — never batch
 * cost. Exactly one version is POS-active; activating copies the price onto
 * `products.salePrice`, and old sales keep their stored historical price.
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

const loading = ref(false)
const busy = ref(false)
const loadError = ref<string | null>(null)
const rows = ref<ProductSalePriceRow[]>([])
const pagination = ref<PaginationState>({ pageIndex: 0, pageSize: 10 })

const addOpen = ref(false)
const addDate = ref(new Date().toISOString().slice(0, 10))
const addPrice = ref<number | undefined>()

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

watch(() => props.product?.id, () => void load(), { immediate: true })
watch(() => props.reloadKey, () => void load())

const canAdd = computed(() =>
  Number(addPrice.value) > 0 && Boolean(String(addDate.value || '').trim()))

async function addVersion() {
  if (!canAdd.value || busy.value || !props.product) return
  busy.value = true
  try {
    await stockQueries.addSalePrice(String(props.product.id), {
      date: String(addDate.value),
      salePrice: Number(addPrice.value),
    })
    addOpen.value = false
    addPrice.value = undefined
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

const versionCell = ({ row }: { row: { original: ProductSalePriceRow } }) =>
  h('span', { class: 'font-medium tabular-nums' }, `v${row.original.version}`)

const priceCell = ({ row }: { row: { original: ProductSalePriceRow } }) =>
  h('span', { class: 'text-end tabular-nums whitespace-nowrap font-medium' }, formatMoney(row.original.salePrice))

const activeCell = ({ row }: { row: { original: ProductSalePriceRow } }) =>
  h(UBadge, {
    color: row.original.isActive ? 'success' : 'neutral',
    variant: 'subtle',
    size: 'sm',
  }, () => row.original.isActive ? t('app.stock.priceHistoryActive') : t('app.stock.priceHistoryInactive'))

const actionCell = ({ row }: { row: { original: ProductSalePriceRow } }) =>
  h(UButton, {
    size: 'xs',
    variant: 'soft',
    color: 'primary',
    icon: 'i-lucide-check',
    label: t('app.stock.priceHistoryActivate'),
    disabled: row.original.isActive || busy.value,
    onClick: () => void activate(row.original),
  })

const columns = computed<TableColumn<ProductSalePriceRow & Record<string, unknown>>[]>(() => [
  {
    accessorKey: 'version',
    header: t('app.stock.version'),
    enableSorting: false,
    cell: versionCell as never,
  },
  {
    accessorKey: 'date',
    header: t('app.fields.date'),
    enableSorting: false,
    meta: { class: { td: 'whitespace-nowrap text-muted', th: '' } },
  },
  {
    accessorKey: 'salePrice',
    header: t('app.stock.salePrice'),
    enableSorting: false,
    cell: priceCell as never,
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
        @click="addOpen = true"
      />
    </div>

    <p v-if="loadError" class="text-sm text-error">{{ loadError }}</p>
    <TableAppListTable
      v-model:pagination="pagination"
      :data="rows"
      :columns="columns"
      :loading="loading"
      :empty-title="t('app.stock.priceHistoryEmpty')"
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
        <CommonAppDateField
          v-model="addDate"
          :label="t('app.fields.date')"
          class="w-full"
        />
        <CommonAppMoneyField
          v-model="addPrice"
          :label="t('app.stock.salePrice')"
          :required="true"
          class="w-full"
        />
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
  </div>
</template>
