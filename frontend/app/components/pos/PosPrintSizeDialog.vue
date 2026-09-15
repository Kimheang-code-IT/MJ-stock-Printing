<script setup lang="ts">
import type { PrintPaperSize } from '~/utils/print/html'

/**
 * Invoice print chooser shown right after a successful POS Submit: the
 * cashier picks A4 or A5 and the bilingual invoice prints in the document's
 * OWN currency (KHR sale → KHR invoice, USD sale → USD invoice), so there is
 * no print-currency switch. Closing/cancelling skips printing; the sale is
 * already saved.
 */
const open = defineModel<boolean>('open', { default: false })

/** True while the parent is printing — blocks duplicate A4/A5 clicks. */
const props = withDefaults(defineProps<{ busy?: boolean }>(), { busy: false })

const emit = defineEmits<{
  confirm: [size: PrintPaperSize]
  cancel: []
}>()

const { t } = useI18n()

/** Two options only; A4 is the default choice (listed/emphasized first). */
const paperOptions: Array<{ value: PrintPaperSize, icon: string, labelKey: string, primary?: boolean }> = [
  { value: 'A4', icon: 'i-lucide-file-text', labelKey: 'app.pos.paperA4', primary: true },
  { value: 'A5', icon: 'i-lucide-file', labelKey: 'app.pos.paperA5' },
]

/** The parent owns closing: it prints on `confirm`, then closes the dialog. */
function choose(size: PrintPaperSize) {
  if (props.busy) return
  emit('confirm', size)
}

/** X / Cancel / Esc / overlay: close without printing (sale already saved). */
function requestCancel() {
  if (props.busy) return
  emit('cancel')
}
</script>

<template>
  <CommonAppDialog
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
          :disabled="busy"
          :loading="busy && option.primary"
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
          :disabled="busy"
          @click="requestCancel"
        />
      </div>
    </template>
  </CommonAppDialog>
</template>
