<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import { useAppHeader } from '~/composables/layout/useAppHeader'
import { useConfirm } from '~/composables/common/useConfirm'
import { useDeliveryCommands, useSettingsRepositories } from '~/repositories/index'
import {
  canTransitionAction,
  deliveryLines,
  deliveryStatusOf,
  noteInvoiceNos,
  noteSales,
  type DeliveryStatusAction,
} from '~/utils/delivery/notes'
import { formatDateTime } from '~/utils/format/format-service'
import { printDeliveryNoteDocument } from '~/utils/print/delivery-note'
import type { AppRecord } from '~/config/admin-seed'

/**
 * Delivery note detail (spec §2.1.9 / §5.13): full fulfillment header
 * (Delivery No, Date, Customer, Phone, Address, Delivery Person, Vehicle /
 * Plate, Status, Note), all linked invoices, per-line delivery quantities,
 * the status timeline (audit history when the data exists) and the
 * status-based actions (Confirm / Out for Delivery / Delivered / Cancel /
 * Print). Delivery never mutates stock.
 */
definePageMeta({
  titleKey: 'app.pages.deliveryNotes',
  permission: 'delivery.view',
})

const route = useRoute()
const store = useAppDataStore()
const auth = useAuthStore()
const { t } = useI18n()
const { setTitle, setBreadcrumbs, clear } = useAppHeader()
const deliveryCommands = useDeliveryCommands()
const { appInfo } = useSettingsRepositories()
const toast = useToast()
const { confirm } = useConfirm()

onBeforeUnmount(clear)

const noteId = computed(() => String(route.params.id || ''))
const loading = ref(false)
const busy = ref(false)
const cancelOpen = ref(false)
const cancelReason = ref('')

const note = computed(() => store.get('deliveryNotes', noteId.value) as AppRecord | null)
const status = computed(() => deliveryStatusOf(note.value))
const lines = computed(() => deliveryLines(note.value))
const shopName = ref('Yoeun Sokhon Pharmacy')

watch(note, (value) => {
  if (!value) return
  setTitle(String(value.deliveryNo || ''))
  setBreadcrumbs([
    { label: t('app.nav.deliveryNotes'), to: '/delivery-notes' },
    { label: String(value.deliveryNo || '') },
  ])
}, { immediate: true })

onMounted(async () => {
  loading.value = true
  try {
    if (!store.get('deliveryNotes', noteId.value)) await store.fetchOne('deliveryNotes', noteId.value)
    await Promise.all([
      store.fetchList('sales'),
      store.fetchList('customers'),
      // Status timeline (best effort): audit rows only exist when the
      // backend/audit history recorded transitions for this note.
      store.fetchList('auditLogs').catch(() => {}),
    ])
    try {
      const info = await appInfo.get()
      const name = String(info.businessName || info.applicationName || '').trim()
      if (name) shopName.value = name
    }
    catch {
      // Keep default shop name when settings are unavailable.
    }
  }
  finally {
    loading.value = false
  }
})

/** Multi-invoice notes (spec §2.1.9): joined display + linked sales. */
const linkedInvoiceNos = computed(() => noteInvoiceNos(note.value))
const linkedSales = computed(() => noteSales(note.value))
const invoiceNoBySaleId = computed(() =>
  new Map(linkedSales.value.map(link => [link.saleId, link.invoiceNo])))

/** Status timeline from the audit trail (hidden when nothing recorded). */
const timeline = computed(() => (store.list('auditLogs') as AppRecord[])
  .filter(row =>
    String(row.entityType || '') === 'DeliveryNote'
    && (String(row.entityId || '') === noteId.value
      || String(row.entityLabel || '') === String(note.value?.deliveryNo || '')))
  .slice(0, 20))

/* ------------------------------ permissions ------------------------------ */

const canConfirm = computed(() => auth.canAccessPage('delivery.confirm'))
const canDeliver = computed(() => auth.canAccessPage('delivery.deliver'))
const canCancel = computed(() => auth.canAccessPage('delivery.cancel'))

function allowed(action: DeliveryStatusAction): boolean {
  return Boolean(note.value) && canTransitionAction(note.value as AppRecord, action)
}

/** Status-based actions (spec §5.13 transitions). */
const statusActions = computed(() => ([
  { action: 'confirm' as const, label: t('app.delivery.actionConfirm'), icon: 'i-lucide-check-circle-2', color: 'primary' as const, enabled: allowed('confirm') && canConfirm.value },
  { action: 'out_for_delivery' as const, label: t('app.delivery.statusOutForDelivery'), icon: 'i-lucide-truck', color: 'warning' as const, enabled: allowed('out_for_delivery') && canDeliver.value },
  { action: 'deliver' as const, label: t('app.delivery.statusDelivered'), icon: 'i-lucide-package-check', color: 'success' as const, enabled: allowed('deliver') && canDeliver.value },
  { action: 'cancel' as const, label: t('app.delivery.actionCancel'), icon: 'i-lucide-circle-off', color: 'error' as const, enabled: allowed('cancel') && canCancel.value },
]).filter(item => item.enabled))

/* ------------------------------ transitions ------------------------------ */

async function runAction(action: DeliveryStatusAction, reason?: string | null) {
  if (busy.value || !note.value) return
  busy.value = true
  try {
    await deliveryCommands.setDeliveryStatus(String(note.value.id), action, reason ?? null)
    await store.fetchOne('deliveryNotes', String(note.value.id))
    toast.add({ title: t('app.delivery.statusUpdated'), color: 'success' })
  }
  catch (error: unknown) {
    toast.add({
      title: t('app.delivery.statusUpdateFailed'),
      description: error instanceof Error ? error.message : String(error),
      color: 'error',
    })
  }
  finally {
    busy.value = false
  }
}

async function cancelNote() {
  const reason = cancelReason.value.trim()
  if (!reason) return
  const ok = await confirm({
    kind: 'generic',
    title: t('app.delivery.actionCancel'),
    description: t('app.delivery.cancelHint'),
    confirmColor: 'error',
  })
  if (!ok) return
  cancelOpen.value = false
  await runAction('cancel', reason)
  cancelReason.value = ''
}

function printNote() {
  if (!note.value) return
  void printDeliveryNoteDocument(note.value, shopName.value)
}

/* -------------------------------- header --------------------------------- */

const headerItems = computed(() => note.value
  ? [
      { label: t('app.delivery.deliveryNo'), value: String(note.value.deliveryNo || '—') },
      { label: t('app.fields.date'), value: note.value.deliveryDate
        ? formatDateTime(note.value.deliveryDate)
        : formatDateTime(note.value.createdAt) },
      { label: t('app.pos.customer'), value: String(note.value.customer || '—') },
      { label: t('app.delivery.deliveryPhone'), value: String(note.value.deliveryPhone || '—') },
      { label: t('app.delivery.deliveryAddress'), value: String(note.value.deliveryLocation || '—') },
      { label: t('app.delivery.driverName'), value: String(note.value.driverName || '—') },
      { label: t('app.delivery.vehicleNo'), value: String(note.value.vehicleNo || '—') },
      { label: t('app.fields.note'), value: String(note.value.note || '—') },
    ]
  : [])

/* ------------------------------ lines table ------------------------------ */

interface DetailLine {
  saleId: string
  invoiceNo: string
  product: string
  uomSymbol: string
  qtyOrdered: number
  qtyToDeliver: number
  qtyDelivered: number
}

const detailLines = computed<DetailLine[]>(() => lines.value.map((line) => {
  const saleId = String(line.saleId || '')
  return {
    saleId,
    invoiceNo: invoiceNoBySaleId.value.get(saleId) || linkedInvoiceNos.value[0] || '—',
    product: String(line.product || ''),
    uomSymbol: String(line.uomSymbol || ''),
    qtyOrdered: Number(line.qtyOrdered ?? 0),
    qtyToDeliver: Number(line.qtyToDeliver ?? 0),
    qtyDelivered: Number(line.qtyDelivered ?? 0),
  }
}))

const lineColumns = computed<TableColumn<DetailLine>[]>(() => [
  { accessorKey: 'invoiceNo', header: t('app.delivery.selectInvoices') },
  { accessorKey: 'product', header: t('app.fields.product') },
  { accessorKey: 'uomSymbol', header: t('app.fields.uom') },
  {
    accessorKey: 'qtyOrdered',
    header: t('app.delivery.qtyOrdered'),
    meta: { class: { td: 'text-end tabular-nums', th: 'text-end' } },
  },
  {
    accessorKey: 'qtyDelivered',
    header: t('app.delivery.qtyDelivered'),
    meta: { class: { td: 'text-end tabular-nums', th: 'text-end' } },
  },
  {
    accessorKey: 'qtyToDeliver',
    header: t('app.delivery.qtyToDeliver'),
    meta: { class: { td: 'text-end tabular-nums', th: 'text-end' } },
  },
])
</script>

<template>
  <div class="flex h-full min-h-0 flex-1 flex-col gap-3 overflow-y-auto bg-muted/20 p-3">
    <p v-if="loading && !note" class="text-sm text-muted">{{ t('common.loading') }}</p>
    <UEmpty
      v-else-if="!note"
      variant="naked"
      icon="i-lucide-package-x"
      :title="t('app.ui.recordNotFound')"
    />

    <template v-else>
      <!-- Header chrome: status badge + status actions + Print -->
      <div class="flex flex-wrap items-center justify-between gap-2 print:hidden">
        <div class="flex items-center gap-2">
          <UBadge
            size="lg"
            variant="subtle"
            :color="status === 'Delivered' ? 'success' : status === 'Cancelled' ? 'error' : status === 'Out for Delivery' ? 'warning' : status === 'Confirmed' ? 'primary' : 'neutral'"
          >
            {{ status }}
          </UBadge>
          <p v-if="note.cancelReason" class="text-xs text-muted">{{ note.cancelReason }}</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <UButton
            v-for="item in statusActions"
            :key="item.action"
            :color="item.color"
            variant="soft"
            size="sm"
            :icon="item.icon"
            :label="item.label"
            :loading="busy"
            @click="item.action === 'cancel' ? (cancelOpen = true) : runAction(item.action)"
          />
          <UButton
            color="neutral"
            variant="outline"
            size="sm"
            icon="i-lucide-printer"
            :label="t('app.delivery.print')"
            @click="printNote"
          />
        </div>
      </div>

      <!-- Fulfillment header: Delivery No / Date / Customer / Phone / Address /
           Delivery Person / Vehicle / Status / Note -->
      <UCard>
        <template #header>
          <p class="text-sm font-medium">{{ t('app.delivery.infoSection') }}</p>
        </template>
        <dl class="grid gap-x-4 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div
            v-for="item in headerItems.filter(item => item.label !== t('app.fields.note'))"
            :key="item.label"
          >
            <dt class="text-[11px] text-muted">{{ item.label }}</dt>
            <dd class="font-medium">{{ item.value }}</dd>
          </div>
        </dl>
        <div
          v-if="String(note.note || '').trim()"
          class="mt-3 border-t border-default pt-3 text-sm"
        >
          <p class="text-[11px] text-muted">{{ t('app.fields.note') }}</p>
          <p class="whitespace-pre-line">{{ note.note }}</p>
        </div>
      </UCard>

      <!-- Linked invoices (one note may cover many invoices of the same customer) -->
      <UCard :ui="{ body: 'p-0 sm:p-0' }">
        <template #header>
          <p class="text-sm font-medium">{{ t('app.delivery.selectInvoices') }}</p>
        </template>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-elevated text-left text-xs text-muted">
              <tr>
                <th class="px-3 py-2 font-medium">{{ t('app.delivery.invoiceCol') }}</th>
                <th class="px-3 py-2 font-medium">{{ t('app.delivery.lines') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="link in linkedSales" :key="link.saleId" class="border-t border-default">
                <td class="px-3 py-2 font-medium">{{ link.invoiceNo || '—' }}</td>
                <td class="px-3 py-2 tabular-nums text-muted">
                  {{ detailLines.filter(line => line.saleId === link.saleId).length }}
                </td>
              </tr>
              <tr v-if="!linkedSales.length">
                <td colspan="2" class="px-3 py-4 text-center text-sm text-muted">
                  {{ linkedInvoiceNos.join(', ') || t('app.ui.noRecords') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </UCard>

      <!-- Item delivery quantities (no stock impact — display only) -->
      <UCard :ui="{ body: 'p-0 sm:p-0' }">
        <template #header>
          <p class="text-sm font-medium">{{ t('app.delivery.lines') }}</p>
        </template>
        <UTable
          :data="detailLines"
          :columns="lineColumns"
          sticky
          class="max-h-[50vh]"
        />
        <p v-if="!detailLines.length" class="px-3 py-4 text-center text-sm text-muted">
          {{ t('app.ui.noRecords') }}
        </p>
      </UCard>

      <!-- Status timeline (audit history, when recorded) -->
      <UCard v-if="timeline.length" :ui="{ body: 'p-0 sm:p-0' }">
        <template #header>
          <p class="text-sm font-medium">{{ t('app.delivery.timeline') }}</p>
        </template>
        <ol class="px-4 py-3">
          <li
            v-for="row in timeline"
            :key="String(row.id)"
            class="flex items-center gap-3 border-l-2 border-default py-1.5 pl-3 text-sm"
          >
            <span class="whitespace-nowrap text-xs text-muted">{{ formatDateTime(row.occurredAt) }}</span>
            <span class="font-medium">{{ row.action }}</span>
            <span class="text-muted">{{ row.user }}</span>
          </li>
        </ol>
      </UCard>
    </template>

    <!-- Cancel reason dialog -->
    <CommonAppDialog
      v-model:open="cancelOpen"
      :title="t('app.delivery.actionCancel')"
      icon="i-lucide-circle-off"
      color="error"
      size="sm"
      :loading="busy"
    >
      <div class="space-y-3">
        <p class="text-sm text-muted">{{ t('app.delivery.cancelHint') }}</p>
        <CommonAppTextareaField
          v-model="cancelReason"
          :label="t('app.delivery.cancelReason')"
          :required="true"
          :rows="3"
          class="w-full"
        />
      </div>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="ghost"
            :label="t('common.cancel')"
            @click="cancelOpen = false"
          />
          <UButton
            color="error"
            icon="i-lucide-circle-off"
            :loading="busy"
            :disabled="!cancelReason.trim()"
            :label="t('app.delivery.actionCancel')"
            @click="cancelNote"
          />
        </div>
      </template>
    </CommonAppDialog>
  </div>
</template>
