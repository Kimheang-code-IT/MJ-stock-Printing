<script setup lang="ts">
import type { PrintPaperSize } from '~/utils/print/html'

/**
 * Invoice print chooser shown right after a successful POS Submit: the
 * cashier picks A4 or A5 and the bilingual invoice prints in the document's
 * OWN currency (KHR sale → KHR invoice, USD sale → USD invoice), so there is
 * no print-currency switch. Choosing a size unmounts this dialog immediately;
 * closing/cancelling without a choice skips printing (sale already saved).
 */
const open = defineModel<boolean>('open', { default: false })

/** True while the parent is printing — blocks duplicate A4/A5 clicks. */
const props = withDefaults(defineProps<{ busy?: boolean }>(), { busy: false })

const emit = defineEmits<{
  confirm: [size: PrintPaperSize]
  cancel: []
}>()

const { t } = useI18n()

/**
 * True after A4/A5 was chosen. Used to (1) tear down the modal via v-if so a
 * blocking `print()` cannot freeze it mid-close, and (2) ignore follow-up
 * close→cancel from the modal shell.
 */
const selected = ref(false)

watch(open, (value) => {
  if (value) selected.value = false
})

/** Two options only; A4 is the default choice (listed/emphasized first). */
const paperOptions: Array<{ value: PrintPaperSize, icon: string, labelKey: string, primary?: boolean }> = [
  { value: 'A4', icon: 'i-lucide-file-text', labelKey: 'app.pos.paperA4', primary: true },
  { value: 'A5', icon: 'i-lucide-file', labelKey: 'app.pos.paperA5' },
]

/** Pick a size: hide this dialog immediately, then let the parent print. */
function choose(size: PrintPaperSize) {
  if (props.busy || selected.value) return
  // Unmount first so the modal cannot freeze on screen when print() blocks.
  selected.value = true
  // Parent confirm() sets printing + open=false sync before first await.
  emit('confirm', size)
  open.value = false
}

/** X / Cancel / Esc / overlay — skipped when we closed ourselves via choose. */
function requestCancel() {
  if (selected.value) return
  emit('cancel')
  open.value = false
}
</script>

<template>
  <!-- v-if={!selected}: tear down on choose so print() cannot freeze a leaving modal. -->
  <CommonAppDialog
    v-if="!selected"
    v-model:open="open"
    :title="t('app.pos.printSizeTitle')"
    icon="i-lucide-printer"
    size="sm"
    @close="requestCancel"
  >
    <div>
      <p class="mb-1.5 text-sm font-medium text-highlighted">
        {{ t('app.pos.paperSize') }}
      </p>
      <div class="grid grid-cols-2 gap-2">
        <UButton
          v-for="option in paperOptions"
          :key="option.value"
          :color="option.primary ? 'primary' : 'neutral'"
          :variant="option.primary ? 'subtle' : 'outline'"
          size="xl"
          :icon="option.icon"
          :label="t(option.labelKey)"
          :disabled="busy || selected"
          class="justify-center"
          @click="choose(option.value)"
        />
      </div>
    </div>

    <template #footer>
      <div class="flex w-full justify-end">
        <UButton
          color="neutral"
          variant="ghost"
          :label="t('common.cancel')"
          :disabled="selected"
          @click="requestCancel"
        />
      </div>
    </template>
  </CommonAppDialog>
</template>
