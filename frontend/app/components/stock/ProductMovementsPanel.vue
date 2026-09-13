<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { PaginationState } from '@tanstack/vue-table'
import { UBadge } from '#components'
import { h } from 'vue'
import type { AppRecord } from '~/config/admin-seed'
import type { ProductHistoryRow } from '~/repositories/contracts/entities'
import { useStockQueries } from '~/repositories/index'

/**
 * Read-only batch-traceable stock movements of one product (product detail
 * Movements tab). Rows come from the immutable movement ledger through the
 * stock-queries repository — loaded only when the tab is open (no global
 * fetch). No edit/delete surface: the ledger is immutable.
 */
const props = withDefaults(defineProps<{
  product?: AppRecord | null
  /** Bump to reload after an external stock op. */
  reloadKey?: number
}>(), {
  product: null,
  reloadKey: 0,
})

const stockQueries = useStockQueries()
const { t } = useI18n()

const search = ref('')
const loading = ref(false)
const loadError = ref<string | null>(null)
const rows = ref<ProductHistoryRow[]>([])
const pagination = ref<PaginationState>({ pageIndex: 0, pageSize: 20 })

async function load() {
  if (!props.product?.id) {
    rows.value = []
    return
  }
  loading.value = true
  loadError.value = null
  try {
    const result = await stockQueries.listProductHistory(String(props.product.id), { limit: 200 })
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

const filteredRows = computed(() => {
  const needle = search.value.trim().toLowerCase()
  if (!needle) return rows.value
  return rows.value.filter(row =>
    [row.reference, row.type, row.batchNo, row.user, row.note]
      .map(value => String(value ?? '').toLowerCase())
      .some(value => value.includes(needle)))
})

const typeCell = ({ row }: { row: { original: ProductHistoryRow } }) =>
  h(UBadge, {
    color: Number(row.original.quantity) >= 0 ? 'success' : 'warning',
    variant: 'subtle',
    size: 'sm',
  }, () => row.original.type)

const batchCell = ({ row }: { row: { original: ProductHistoryRow } }) =>
  h('span', { class: 'font-medium whitespace-nowrap' }, row.original.batchNo || '—')

const expiryCell = ({ row }: { row: { original: ProductHistoryRow } }) =>
  h('span', { class: 'whitespace-nowrap text-muted tabular-nums' }, row.original.expiryDate || '—')

const qtyInCell = ({ row }: { row: { original: ProductHistoryRow } }) =>
  h('span', { class: 'text-end tabular-nums whitespace-nowrap' },
    Number(row.original.quantity) > 0 ? String(row.original.quantity) : '')

const qtyOutCell = ({ row }: { row: { original: ProductHistoryRow } }) =>
  h('span', { class: 'text-end tabular-nums whitespace-nowrap' },
    Number(row.original.quantity) < 0 ? String(Math.abs(Number(row.original.quantity))) : '')

const columns = computed<TableColumn<ProductHistoryRow & Record<string, unknown>>[]>(() => [
  {
    accessorKey: 'date',
    header: t('app.fields.date'),
    enableSorting: false,
    meta: { class: { td: 'whitespace-nowrap text-muted', th: '' } },
  },
  {
    accessorKey: 'reference',
    header: t('app.stock.documentNoCol'),
    enableSorting: false,
    cell: ({ row }) => h('span', { class: 'font-medium whitespace-nowrap' }, String(row.original.reference || '—')) as never,
  },
  {
    accessorKey: 'batchNo',
    header: t('app.stock.batchNo'),
    enableSorting: false,
    cell: batchCell as never,
  },
  {
    accessorKey: 'expiryDate',
    header: t('app.stock.expiryDateCol'),
    enableSorting: false,
    cell: expiryCell as never,
  },
  {
    accessorKey: 'type',
    header: t('app.stock.movementType'),
    enableSorting: false,
    cell: typeCell as never,
  },
  {
    accessorKey: 'unit',
    header: t('app.pos.uom'),
    enableSorting: false,
    meta: { class: { td: 'whitespace-nowrap text-muted', th: '' } },
  },
  {
    accessorKey: '__in',
    header: t('app.stock.qtyIn'),
    enableSorting: false,
    cell: qtyInCell as never,
  },
  {
    accessorKey: '__out',
    header: t('app.stock.qtyOut'),
    enableSorting: false,
    cell: qtyOutCell as never,
  },
  {
    accessorKey: 'user',
    header: t('app.fields.user'),
    enableSorting: false,
    cell: ({ row }) => h('span', { class: 'text-muted whitespace-nowrap' }, String(row.original.user || '—')) as never,
  },
])
</script>

<template>
  <div class="flex flex-col gap-2">
    <p v-if="loadError" class="text-sm text-error">{{ loadError }}</p>
    <TableAppListTable
      v-model:search="search"
      v-model:pagination="pagination"
      :data="filteredRows"
      :columns="columns"
      :loading="loading"
      :empty-title="t('app.ui.noRecords')"
    />
  </div>
</template>
