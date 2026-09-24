<script setup lang="ts">
import type { DropdownMenuItem } from '@nuxt/ui'
import type { AppConfig } from '~/types/mj/settings'
import { systemSettingsTabs } from '~/config/settings-schemas'
import { useSettingsRepositories } from '~/repositories'
import { useConfirm } from '~/composables/common/useConfirm'
import { useAppPageTitle } from '~/composables/layout/useAppPageTitle'
import { getByPath, setByPath } from '~/utils/object-path'
import { useAppLocalization } from '~/composables/settings/useAppLocalization'

const { appConfig } = useSettingsRepositories()
const { t } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const auth = useAuthStore()
const canEdit = computed(() => auth.canAccessPage('settings.update'))
const canConfigure = computed(() => auth.canAccessPage('settings.update'))
const appLocalization = useAppLocalization()

const pending = ref(true)
const saving = ref(false)
const testingEmail = ref(false)
const testingTelegram = ref(false)
const resettingData = ref(false)
const clearingTransactions = ref(false)
const runningBackup = ref(false)
const activeTab = ref('localization')
const model = ref<AppConfig | null>(null)

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback
}

async function load() {
  pending.value = true
  try {
    model.value = await appConfig.get()
  }
  catch (error: unknown) {
    toast.add({ title: errorMessage(error, t('core.common.loadFailed')), color: 'error' })
  }
  finally {
    pending.value = false
  }
}

function fieldValue(key: string): unknown {
  if (!model.value) return undefined

  // Select options use string values; coerce number fields for USelect match.
  if (key === 'general.defaultPageSize' || key === 'system.paginationDefault') {
    const raw = getByPath(model.value, key)
    return raw == null || raw === '' ? undefined : String(raw)
  }

  if (key === 'backup.intervalHours') {
    const raw = getByPath(model.value, key)
    return raw == null || raw === '' ? undefined : String(raw)
  }

  // The notifications tab's language selector maps onto the shared
  // telegram message language (backend `notification_language`).
  if (key === 'telegram.notificationLanguage') {
    const raw = model.value.telegram.messageLanguage
    return raw == null ? undefined : String(raw)
  }

  return getByPath(model.value, key)
}

async function setFieldValue(key: string, value: unknown) {
  if (!model.value) return

  if (key === 'system.maintenanceMode' || key === 'system.readOnlyMode') {
    if (value === true) {
      const ok = await confirm({
        kind: 'update',
        titleKey: 'core.settings.confirmModeTitle',
        descriptionKey: 'core.settings.confirmModeHelp',
        confirmColor: 'warning',
      })
      if (!ok) return
    }
    setByPath(model.value, key, value)
    return
  }

  if (key === 'general.defaultPageSize' || key === 'system.paginationDefault') {
    const n = Number(value)
    setByPath(model.value, key, Number.isFinite(n) ? n : 20)
    return
  }

  if (key === 'backup.intervalHours') {
    const n = Number(value)
    setByPath(model.value, key, Number.isFinite(n) ? n : 24)
    return
  }

  if (key === 'telegram.notificationLanguage') {
    setByPath(model.value, 'telegram.messageLanguage', value === 'km' ? 'km' : 'en')
    return
  }

  setByPath(model.value, key, value)
}

async function save() {
  if (!model.value) return
  saving.value = true
  try {
    model.value = await appConfig.update(model.value)
    appLocalization.apply(model.value.localization)
    usePreferencesStore().setCurrency(model.value.localization.currency)
    usePreferencesStore().syncLocaleWithConfig()
    toast.add({ title: t('core.common.saved'), color: 'success' })
  }
  catch (error: unknown) {
    toast.add({ title: errorMessage(error, t('core.common.saveFailed')), color: 'error' })
  }
  finally {
    saving.value = false
  }
}

async function testEmail() {
  testingEmail.value = true
  try {
    if (model.value) await appConfig.update({ email: model.value.email })
    const result = await appConfig.testEmailConnection()
    model.value = await appConfig.get()
    toast.add({
      title: result.message,
      color: result.status === 'connected' ? 'success' : 'error',
    })
  }
  finally {
    testingEmail.value = false
  }
}

async function testTelegram() {
  testingTelegram.value = true
  try {
    if (model.value) await appConfig.update({ telegram: model.value.telegram })
    const result = await appConfig.sendTestTelegramMessage()
    model.value = await appConfig.get()
    toast.add({
      title: result.message,
      color: result.status === 'connected' ? 'success' : 'error',
    })
  }
  finally {
    testingTelegram.value = false
  }
}

async function resetAllData() {
  const ok = await confirm({
    kind: 'generic',
    titleKey: 'core.settings.resetDataConfirmTitle',
    descriptionKey: 'core.settings.resetDataConfirmHelp',
    confirmLabelKey: 'core.settings.resetDataAction',
    confirmColor: 'error',
  })
  if (!ok) return

  resettingData.value = true
  try {
    await appConfig.resetAllData()
    toast.add({ title: t('core.settings.resetDataSuccess'), color: 'success' })
    await auth.logout()
  }
  catch (error: unknown) {
    toast.add({ title: errorMessage(error, t('core.settings.resetDataFailed')), color: 'error' })
  }
  finally {
    resettingData.value = false
  }
}

/** Delete every sales + purchase transaction and zero stock (master data kept). */
async function clearTransactions() {
  const ok = await confirm({
    kind: 'generic',
    titleKey: 'core.settings.clearTransactionsConfirmTitle',
    descriptionKey: 'core.settings.clearTransactionsConfirmHelp',
    confirmLabelKey: 'core.settings.clearTransactionsAction',
    confirmColor: 'error',
  })
  if (!ok) return

  clearingTransactions.value = true
  try {
    await appConfig.clearTransactions()
    toast.add({ title: t('core.settings.clearTransactionsSuccess'), color: 'success' })
  }
  catch (error: unknown) {
    toast.add({ title: errorMessage(error, t('core.settings.clearTransactionsFailed')), color: 'error' })
  }
  finally {
    clearingTransactions.value = false
  }
}

/** Trigger an immediate Google Sheets backup and refresh the run summary. */
async function runBackup() {
  runningBackup.value = true
  try {
    const result = await appConfig.runBackupNow()
    const ok = result.status === 'SUCCESS'
    toast.add({
      title: ok ? t('core.settings.backupRunSuccess') : t('core.settings.backupRunFailed'),
      color: ok ? 'success' : 'error',
    })
    model.value = await appConfig.get()
  }
  catch (error: unknown) {
    toast.add({ title: errorMessage(error, t('core.settings.backupRunFailed')), color: 'error' })
  }
  finally {
    runningBackup.value = false
  }
}

/** Destructive maintenance actions live behind the header ⋯ menu. */
const dangerItems = computed<DropdownMenuItem[][]>(() => {
  if (!canConfigure.value) return []
  return [[
    {
      label: t('core.settings.resetDataAction'),
      icon: 'i-lucide-database-zap',
      color: 'error',
      disabled: resettingData.value,
      onSelect: () => { void resetAllData() },
    },
    {
      label: t('core.settings.clearTransactionsAction'),
      icon: 'i-lucide-trash-2',
      color: 'error',
      disabled: clearingTransactions.value,
      onSelect: () => { void clearTransactions() },
    },
  ]]
})

onMounted(() => void load())
useAppPageTitle(() => t('app.pages.settings'))
</script>

<template>
  <DocumentAppDocumentPage
    v-model:active-tab="activeTab"
    :tabs="systemSettingsTabs"
    :field-value="fieldValue"
    :set-field-value="setFieldValue"
    :pending="pending || !model"
    :saving="saving"
    :read-only="!canEdit"
    :can-save="canEdit"
    :show-list-nav="false"
    :more-items="dangerItems"
    content-wide
    @save="save"
    @refresh="load"
  >
    <template #actions>
      <CommonAppConnectionTestButton
        v-if="activeTab === 'email' && canConfigure"
        :loading="testingEmail"
        @click="testEmail"
      />
      <CommonAppConnectionTestButton
        v-if="activeTab === 'telegram' && canConfigure"
        :loading="testingTelegram"
        @click="testTelegram"
      />
      <UButton
        v-if="activeTab === 'backup' && canConfigure"
        icon="i-lucide-cloud-upload"
        :loading="runningBackup"
        :label="t('core.settings.backupRunNow')"
        @click="runBackup"
      />
    </template>
  </DocumentAppDocumentPage>
</template>
