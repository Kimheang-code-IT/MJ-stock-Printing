<script setup lang="ts">
import { UInputNumber } from '#components'
import { currencySymbol } from '~/utils/format/format-service'

/**
 * Money input: a numeric field with the currency symbol (`$` / `៛`) rendered
 * at the end of the field. The symbol follows the record/document currency
 * when provided, otherwise the System Settings default.
 */
const props = withDefaults(defineProps<{
  modelValue?: number | null | undefined
  /** Record/document currency; falls back to the shop default when omitted. */
  currency?: string | null
  name?: string
  placeholder?: string
  min?: number
  max?: number
  step?: number
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  disabled?: boolean
  readonly?: boolean
  class?: string
  ui?: Record<string, unknown>
  align?: 'left' | 'right'
}>(), {
  step: 0.01,
  size: 'md',
  align: 'left',
})

const emit = defineEmits<{
  'update:modelValue': [number | undefined]
  blur: [FocusEvent]
  focus: [FocusEvent]
}>()

const symbol = computed(() => currencySymbol(props.currency ?? undefined))
/** `pe-7` keeps the number clear of the absolutely-positioned currency symbol. */
const baseUi = computed(() => ({
  base: `pe-7 tabular-nums ${props.align === 'right' ? 'text-right' : ''} ${String(props.ui?.base ?? '')}`.trim(),
}))
</script>

<template>
  <div
    class="relative"
    :class="$props.class"
  >
    <UInputNumber
      :model-value="modelValue"
      :name="name"
      :placeholder="placeholder"
      :min="min"
      :max="max"
      :step="step"
      :size="size"
      :disabled="disabled"
      :readonly="readonly"
      :increment="false"
      :decrement="false"
      class="w-full"
      :ui="baseUi"
      @update:model-value="emit('update:modelValue', $event ?? undefined)"
      @blur="emit('blur', $event)"
      @focus="emit('focus', $event)"
    />
    <span class="pointer-events-none absolute inset-y-0 right-2 flex items-center text-sm text-muted">{{ symbol }}</span>
  </div>
</template>
