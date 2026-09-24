<script setup lang="ts">
import { CommonAppField, UButton, UFieldGroup, UInputNumber } from '#components'
import { currencySymbol } from '~/utils/format/format-service'

/**
 * Reusable money/decimal input.
 *
 * - Labeled form field (default): wraps the control in `CommonAppField`.
 * - `inline`: renders the bare control for table cells / tight rows.
 * - `currency`: code shown as a symbol suffix (`$` / `៛`), defaults to shop currency.
 * - `currencyToggle`: renders a USD/KHR toggle instead of a fixed symbol.
 */
const props = withDefaults(defineProps<{
  modelValue?: number | null | undefined
  label?: string
  labelKey?: string
  name?: string
  placeholder?: string
  required?: boolean
  disabled?: boolean
  readonly?: boolean
  help?: string
  helpKey?: string
  error?: string | boolean
  min?: number
  max?: number
  step?: number
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  class?: string
  /** Text alignment of the numeric value. */
  align?: 'left' | 'right'
  /** Extra `UInputNumber` ui slots (e.g. `{ base: '...' }`). */
  ui?: Record<string, unknown>
  /** Currency code shown as the field symbol; falls back to the shop default. */
  currency?: string | null
  /** When set, renders a USD/KHR toggle instead of a fixed symbol. */
  currencyToggle?: boolean
  /** Render the bare control (no label wrapper) for table/inline use. */
  inline?: boolean
}>(), {
  min: 0,
  step: 0.01,
  size: 'md',
  align: 'left',
  currencyToggle: false,
  inline: false,
})

const emit = defineEmits<{
  'update:modelValue': [number | undefined]
  'update:currency': ['USD' | 'KHR']
  blur: [FocusEvent]
  focus: [FocusEvent]
}>()

const { t } = useI18n()

const currencyOptions = [
  { value: 'USD' as const, symbol: '$', labelKey: 'app.pos.currencyUsd' },
  { value: 'KHR' as const, symbol: '៛', labelKey: 'app.pos.currencyKhr' },
]

const value = computed({
  get: () => props.modelValue ?? undefined,
  set: (v: number | undefined) => emit('update:modelValue', v),
})

const moneySymbol = computed(() => currencySymbol(props.currency ?? undefined))

const inputUi = computed(() => ({
  ...props.ui,
  base: `${props.currencyToggle ? '' : 'pe-7'} ${props.align === 'right' ? 'text-right' : ''} ${String(props.ui?.base ?? '')}`.trim(),
}))

const inputClass = computed(() => [props.class, fieldControlClass(Boolean(props.error))])

const wrapperProps = computed(() => props.inline
  ? { class: props.class }
  : {
      label: props.label,
      labelKey: props.labelKey,
      name: props.name,
      required: props.required,
      help: props.help,
      helpKey: props.helpKey,
      error: props.error,
    })

function onCurrencySelect(currency: 'USD' | 'KHR') {
  if (currency !== props.currency) emit('update:currency', currency)
}
</script>

<template>
  <component
    :is="inline ? 'div' : CommonAppField"
    v-bind="wrapperProps"
  >
    <UFieldGroup
      v-if="currencyToggle"
      :size="size"
      class="w-full"
    >
      <UInputNumber
        v-model="value"
        :name="name"
        :placeholder="placeholder"
        :required="required"
        :disabled="disabled"
        :readonly="readonly"
        :min="min"
        :max="max"
        :step="step"
        :size="size"
        :increment="false"
        :decrement="false"
        :ui="inputUi"
        :class="[$props.class, fieldControlClass(Boolean(error))]"
        @blur="emit('blur', $event)"
        @focus="emit('focus', $event)"
      />
      <UButton
        v-for="option in currencyOptions"
        :key="option.value"
        :label="option.symbol"
        :color="currency === option.value ? 'primary' : 'neutral'"
        :variant="currency === option.value ? 'soft' : 'outline'"
        :disabled="disabled"
        :title="t(option.labelKey)"
        :aria-label="t(option.labelKey)"
        :aria-pressed="currency === option.value"
        @click="onCurrencySelect(option.value)"
      />
    </UFieldGroup>

    <div
      v-else
      class="relative w-full"
    >
      <UInputNumber
        v-model="value"
        :name="name"
        :placeholder="placeholder"
        :required="required"
        :disabled="disabled"
        :readonly="readonly"
        :min="min"
        :max="max"
        :step="step"
        :size="size"
        :increment="false"
        :decrement="false"
        :ui="inputUi"
        :class="inputClass"
        @blur="emit('blur', $event)"
        @focus="emit('focus', $event)"
      />
      <span class="pointer-events-none absolute inset-y-0 right-2 flex items-center text-sm text-muted">{{ moneySymbol }}</span>
    </div>
  </component>
</template>
