<script setup lang="ts">
import type { ExportFieldOption, ExportFormat, ExportRequest } from '~/types/mj/export'

const open = defineModel<boolean>('open', { default: false })

const props = withDefaults(defineProps<{
  fields?: ExportFieldOption[]
  selectedCount?: number
  loading?: boolean
  /** Debt reports: when set, offer "export for one party" + a party picker. */
  partyOptions?: ExportFieldOption[]
  partyLabel?: string
  /** Debt reports: when set, offer a staff-user filter. */
  userOptions?: ExportFieldOption[]
  userLabel?: string
}>(), {
  fields: () => [],
  selectedCount: 0,
  loading: false,
  partyOptions: () => [],
  partyLabel: '',
  userOptions: () => [],
  userLabel: '',
})

const emit = defineEmits<{
  submit: [request: ExportRequest]
}>()

const { t } = useI18n()
const startDate = ref('')
const endDate = ref('')
const format = ref<ExportFormat>('xlsx')
const selectedFields = ref<string[]>([])
const oneParty = ref(false)
const partyId = ref('')
const userId = ref('')

const formatItems = computed(() => [
  { label: t('core.exportDialog.formatExcel'), value: 'xlsx' },
  { label: t('core.exportDialog.formatPdf'), value: 'pdf' },
])

const userSelectItems = computed(() => [
  { label: t('core.exportDialog.allUsers'), value: '' },
  ...props.userOptions,
])

const invalidRange = computed(() => Boolean(
  startDate.value && endDate.value && startDate.value > endDate.value,
))
const noFields = computed(() => props.fields.length > 0 && selectedFields.value.length === 0)
const partyMissing = computed(() => oneParty.value && !partyId.value)
const canSubmit = computed(() =>
  !invalidRange.value && !noFields.value && !partyMissing.value && !props.loading)

watch(open, (isOpen) => {
  if (!isOpen) return
  startDate.value = ''
  endDate.value = ''
  format.value = 'xlsx'
  selectedFields.value = props.fields.map(field => field.value)
  oneParty.value = false
  partyId.value = ''
  userId.value = ''
})

function toggleField(value: string, checked: boolean | 'indeterminate') {
  selectedFields.value = checked === true
    ? [...new Set([...selectedFields.value, value])]
    : selectedFields.value.filter(field => field !== value)
}

function submit() {
  if (!canSubmit.value) return
  emit('submit', {
    startDate: startDate.value || undefined,
    endDate: endDate.value || undefined,
    // Exports always cover the rows currently shown on the page.
    scope: 'current_page',
    fieldCodes: [...selectedFields.value],
    format: format.value,
    partyId: oneParty.value && partyId.value ? partyId.value : undefined,
    userId: userId.value || undefined,
  })
}
</script>

<template>
  <CommonAppDialog
    v-model:open="open"
    :title="$t('core.exportDialog.title')"
    :loading="loading"
    width="2xl"
  >
    <div class="space-y-5">
      <div class="grid gap-3 sm:grid-cols-2">
        <CommonAppDateField
          v-model="startDate"
          :label="$t('core.exportDialog.startDate')"
          granularity="day"
          class="w-full"
        />
        <CommonAppDateField
          v-model="endDate"
          :label="$t('core.exportDialog.endDate')"
          granularity="day"
          :error="invalidRange ? $t('core.exportDialog.invalidRange') : undefined"
          class="w-full"
        />
      </div>

      <UFormField :label="$t('core.exportDialog.format')">
        <USelect
          v-model="format"
          :items="formatItems"
          value-key="value"
          class="w-full"
        />
      </UFormField>

      <div v-if="partyOptions.length || userOptions.length" class="grid gap-4 sm:grid-cols-2">
        <div v-if="partyOptions.length" class="space-y-2">
          <UCheckbox
            v-model="oneParty"
            :label="$t('core.exportDialog.oneParty', { party: partyLabel })"
          />
          <USelect
            v-if="oneParty"
            v-model="partyId"
            :items="partyOptions"
            value-key="value"
            :placeholder="$t('core.exportDialog.selectParty', { party: partyLabel })"
            class="w-full"
          />
        </div>
        <UFormField v-if="userOptions.length" :label="userLabel">
          <USelect
            v-model="userId"
            :items="userSelectItems"
            value-key="value"
            class="w-full"
          />
        </UFormField>
      </div>

      <fieldset v-if="fields.length" class="rounded-sm border border-default p-3">
        <legend class="px-1 text-sm font-medium text-highlighted">
          {{ $t('core.exportDialog.fields') }}
        </legend>
        <div class="grid gap-2 sm:grid-cols-2">
          <UCheckbox
            v-for="field in fields"
            :key="field.value"
            :model-value="selectedFields.includes(field.value)"
            :label="field.label"
            @update:model-value="toggleField(field.value, $event)"
          />
        </div>
        <p v-if="noFields" class="mt-2 text-xs text-error">
          {{ $t('core.exportDialog.fieldRequired') }}
        </p>
      </fieldset>
    </div>

    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton
          color="neutral"
          variant="ghost"
          :disabled="loading"
          @click="open = false"
        >
          {{ $t('actions.cancel') }}
        </UButton>
        <UButton
          icon="i-lucide-download"
          :loading="loading"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ $t('actions.export') }}
        </UButton>
      </div>
    </template>
  </CommonAppDialog>
</template>
