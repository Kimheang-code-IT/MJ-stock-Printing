<script setup lang="ts">
import { useAppHeader } from '~/composables/layout/useAppHeader'
import { useSettingsRepositories } from '~/repositories/index'
import { isDeliveryEditable } from '~/utils/delivery/notes'
import type { AppRecord } from '~/config/admin-seed'

/**
 * Delivery note detail (spec §2.1.9 / §5.13): renders as the shared document
 * page (`frontend/app/components/document` via DeliveryNoteCreateFlow) with
 * the same update logic as the product document. Draft notes are editable;
 * other statuses render read-only. No status/print action buttons.
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
const { appInfo } = useSettingsRepositories()

onBeforeUnmount(clear)

const noteId = computed(() => String(route.params.id || ''))
const loading = ref(false)

const note = computed(() => store.get('deliveryNotes', noteId.value) as AppRecord | null)
const shopName = ref('MJ Printing')

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

/* ------------------------------ permissions ------------------------------ */

const canConfirm = computed(() => auth.canAccessPage('delivery.confirm'))
/** Draft + delivery.update — the only state the edit form may save. */
const canEditNote = computed(() => Boolean(note.value)
  && isDeliveryEditable(note.value as AppRecord)
  && auth.canAccessPage('delivery.update'))

/** The note was edited in place — refresh it and stay on this page. */
async function onNoteSaved() {
  await store.fetchOne('deliveryNotes', noteId.value)
}
</script>

<template>
  <!-- The note renders as the shared document page (frontend/app/components/document):
       full-page General + Lines form with the document header/actions. Draft
       notes are editable with the same save logic as /delivery-notes/new. -->
  <DeliveryNoteCreateFlow
    v-if="note"
    :key="noteId"
    :edit-note="note"
    :can-confirm="canConfirm"
    :can-update="canEditNote"
    :print-on-create="false"
    :shop-name="shopName"
    @created="onNoteSaved"
  />

  <p
    v-else-if="loading"
    class="flex h-full items-center justify-center text-sm text-muted"
  >
    {{ t('common.loading') }}
  </p>

  <UEmpty
    v-else
    variant="naked"
    icon="i-lucide-package-x"
    :title="t('app.ui.recordNotFound')"
  />
</template>
