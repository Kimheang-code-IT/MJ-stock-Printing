<script setup lang="ts">
import { formatMoney } from '~/composables/module/useModule'
import type { PosCartLine } from '~/utils/pos/cart'
import { cartSubtotal, lineAreaM2, lineNet } from '~/utils/pos/cart'

const props = withDefaults(defineProps<{
  cart: PosCartLine[]
  disabled?: boolean
  /** ONE sale currency for the whole cart (USD | KHR) — header selector. */
  saleCurrency?: 'USD' | 'KHR'
  /** Return mode: the original price is preserved (read-only);
   *  only the return quantity is editable. */
  returnMode?: boolean
}>(), {
  disabled: false,
  saleCurrency: 'USD',
  returnMode: false,
})

const emit = defineEmits<{
  changeQty: [productId: string, delta: number]
  updateDimensions: [productId: string, height: number | undefined, width: number | undefined]
  updatePrice: [productId: string, unitPrice: number]
  updateSaleCurrency: [value: 'USD' | 'KHR']
  remove: [productId: string]
  clear: []
  back: []
  next: []
}>()

const { t } = useI18n()

const currencyOptions = [
  { value: 'USD' as const, symbol: '$', labelKey: 'app.pos.currencyUsd' },
  { value: 'KHR' as const, symbol: '៛', labelKey: 'app.pos.currencyKhr' },
]

/** Cart amounts are stored in the sale currency — no conversion here. */
const money = (value: unknown) => formatMoney(Number(value || 0), props.saleCurrency)
const subtotal = computed(() => cartSubtotal(props.cart))

/** Area in m² shown for a line, or null for a plain count line. */
function lineArea(line: PosCartLine): number | null {
  return line.areaM2 ?? lineAreaM2(line)
}

function onDimensionInput(line: PosCartLine, field: 'height' | 'width', value: unknown) {
  const parsed = value == null || value === '' ? undefined : Number(value)
  const amount = parsed != null && Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
  const height = field === 'height' ? amount : line.height
  const width = field === 'width' ? amount : line.width
  emit('updateDimensions', line.productId, height, width)
}

function onPriceInput(line: PosCartLine, value: unknown) {
  const amount = Number(value ?? 0)
  emit('updatePrice', line.productId, Number.isFinite(amount) ? Math.max(0, amount) : 0)
}
</script>

<template>
  <section class="flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-default lg:w-[55%] lg:flex-none lg:border-l lg:border-default">
    <div class="flex items-center justify-between border-b border-default px-3 py-2.5">
      <div class="flex items-center gap-2">
        <h2 class="text-sm font-semibold">
          {{ t('app.pos.cart') }}
          <span
            v-if="cart.length"
            class="ml-1 text-muted"
          >({{ cart.length }})</span>
        </h2>
        <!-- Global sale-currency selector: drives every cart amount. -->
        <UFieldGroup>
          <UButton
            v-for="option in currencyOptions"
            :key="option.value"
            size="xs"
            :label="option.symbol"
            :color="saleCurrency === option.value ? 'primary' : 'neutral'"
            :variant="saleCurrency === option.value ? 'soft' : 'outline'"
            :disabled="disabled || returnMode"
            :title="t(option.labelKey)"
            :aria-label="t(option.labelKey)"
            :aria-pressed="saleCurrency === option.value"
            @click="emit('updateSaleCurrency', option.value)"
          />
        </UFieldGroup>
      </div>
      <UButton
        size="xs"
        color="neutral"
        variant="ghost"
        :disabled="!cart.length || disabled"
        :label="t('app.pos.clearCart')"
        @click="emit('clear')"
      />
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <!-- Column headers: image · product · unit price · qty · amount · remove. -->
      <div class="flex items-center gap-x-2 border-b border-default bg-elevated/40 px-2 text-[10px] font-semibold uppercase tracking-wide text-muted">
        <span class="size-9 shrink-0" />
        <span class="min-w-0 flex-1">{{ t('app.pos.product') }}</span>
        <span class="w-40 shrink-0 text-center">{{ t('app.pos.height') }} / {{ t('app.pos.width') }}</span>
        <span class="w-14 shrink-0 text-center">{{ t('app.pos.areaM2') }}</span>
        <span class="w-32 shrink-0 text-right">{{ t('app.pos.unitPrice') }}</span>
        <span class="w-28 shrink-0 text-center">{{ t('app.pos.qty') }}</span>
        <span class="w-28 shrink-0 text-right">{{ t('app.pos.amount') }}</span>
        <span class="w-7 shrink-0" />
      </div>

      <!-- One row per line: image · name · unit price · qty · total · remove. -->
      <div
        v-for="line in cart"
        :key="line.productId"
        class="flex flex-wrap items-center gap-x-2 gap-y-1.5 border-b border-default px-2 py-2"
      >
        <div class="size-9 shrink-0 overflow-hidden rounded-sm bg-elevated">
          <img
            v-if="line.imageUrl"
            :src="line.imageUrl"
            :alt="line.name"
            class="h-full w-full object-cover"
          >
          <div
            v-else
            class="flex h-full w-full items-center justify-center text-muted"
          >
            <UIcon
              name="i-lucide-package"
              class="size-4 opacity-40"
            />
          </div>
        </div>

        <p class="min-w-0 flex-1 truncate text-sm font-medium">
          {{ line.name }}
        </p>

        <!-- Sold-by-area: Height × Width (metres) → billed m². -->
        <div class="flex w-40 shrink-0 items-center justify-center gap-1">
          <UInput
            :model-value="line.height"
            type="number"
            min="0"
            step="0.01"
            size="sm"
            class="app-no-spinner w-16"
            :placeholder="t('app.pos.heightShort')"
            :disabled="disabled || returnMode"
            @update:model-value="onDimensionInput(line, 'height', $event)"
          />
          <UInput
            :model-value="line.width"
            type="number"
            min="0"
            step="0.01"
            size="sm"
            class="app-no-spinner w-20"
            :placeholder="t('app.pos.widthShort')"
            :disabled="disabled || returnMode"
            @update:model-value="onDimensionInput(line, 'width', $event)"
          />
        </div>
        <span class="w-14 shrink-0 text-center text-sm tabular-nums">
          {{ lineArea(line) == null ? '—' : lineArea(line) }}
        </span>

        <!-- Unit price: inline direct edit. -->
        <CommonAppMoneyField
          inline
          :model-value="line.unitPrice"
          :currency="saleCurrency"
          :min="0"
          :step="0.01"
          size="md"
          align="right"
          class="w-32 shrink-0"
          :disabled="disabled || returnMode"
          @update:model-value="onPriceInput(line, $event)"
        />

        <!-- Quantity: area lines are derived from H × W; others use the stepper. -->
        <div class="flex w-28 shrink-0 items-center justify-center">
          <template v-if="lineArea(line) != null">
            <span class="text-sm font-medium tabular-nums">{{ line.quantity }}</span>
          </template>
          <template v-else>
            <UButton
              size="sm"
              color="primary"
              variant="solid"
              icon="i-lucide-minus"
              square
              :disabled="disabled || line.quantity <= 1"
              @click="emit('changeQty', line.productId, -1)"
            />
            <span class="min-w-7 text-center text-sm font-medium tabular-nums">{{ line.quantity }}</span>
            <UButton
              size="sm"
              color="primary"
              variant="solid"
              icon="i-lucide-plus"
              square
              :disabled="disabled || line.quantity >= line.availableStock"
              @click="emit('changeQty', line.productId, 1)"
            />
          </template>
        </div>

        <span class="w-28 shrink-0 text-right text-sm font-semibold tabular-nums">
          {{ money(lineNet(line)) }}
        </span>

        <!-- Remove line (end of row, red). -->
        <UButton
          size="sm"
          color="error"
          variant="ghost"
          icon="i-lucide-trash-2"
          square
          class="w-7 shrink-0"
          :disabled="disabled"
          :aria-label="t('app.pos.removeItem')"
          @click="emit('remove', line.productId)"
        />
      </div>

      <p
        v-if="!cart.length"
        class="p-4 text-sm text-muted"
      >
        {{ t('app.pos.emptyCart') }}
      </p>
    </div>

    <!-- Subtotal + Back / Next. -->
    <div class="border-t border-default px-3 py-2.5">
      <div class="flex items-center justify-between">
        <span class="text-sm font-semibold uppercase">{{ t('app.pos.subtotal') }}</span>
        <span class="text-lg font-bold tabular-nums">{{ money(subtotal) }}</span>
      </div>
      <div class="mt-2 flex gap-2">
        <UButton
          class="h-12 flex-1 justify-center"
          color="neutral"
          variant="soft"
          icon="i-lucide-arrow-left"
          :label="t('common.back')"
          @click="emit('back')"
        />
        <UButton
          class="h-12 flex-1 justify-center"
          color="primary"
          icon="i-lucide-arrow-right"
          trailing
          :disabled="!cart.length || disabled"
          :label="t('app.pos.next')"
          @click="emit('next')"
        />
      </div>
    </div>
  </section>
</template>
