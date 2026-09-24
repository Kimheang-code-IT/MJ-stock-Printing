<script setup lang="ts">
import type { DropdownMenuItem } from '@nuxt/ui'
import type { TableRowMetaAction } from '~/utils/table/list-columns'

withDefaults(defineProps<{
  items: DropdownMenuItem[][]
  actions?: TableRowMetaAction[]
  loading?: boolean
}>(), {
  actions: () => [],
  loading: false,
})

const { t } = useI18n()
</script>

<template>
  <div class="flex items-center justify-end gap-0.5">
    <UButton
      v-for="(action, index) in actions"
      :key="index"
      :icon="action.icon"
      color="neutral"
      variant="ghost"
      size="xs"
      :disabled="action.disabled"
      :title="action.label"
      :aria-label="action.label"
      @click="action.onClick()"
    />
    <UDropdownMenu
      v-if="items.length"
      :items="items"
      :content="{ align: 'end' }"
      :aria-label="t('app.ui.actions')"
    >
      <UButton
        icon="i-lucide-ellipsis"
        color="neutral"
        variant="ghost"
        size="xs"
        :loading="loading"
        :aria-label="t('app.ui.actions')"
      />
    </UDropdownMenu>
  </div>
</template>
