<script setup lang="ts">
/**
 * Toolbar sort control: an icon-only button that opens a menu of sortable
 * fields. Date fields offer old→new / new→old; document-number (and other
 * numeric) fields offer small→large / large→small; text fields offer A→Z.
 */
import type { DropdownMenuItem } from '@nuxt/ui'
import type { ListTableSort, ListTableSortKind, ListTableSortOption } from '~/utils/table/list-table'

const props = withDefaults(defineProps<{
  options: ListTableSortOption[]
  label?: string
}>(), {
  label: '',
})

const sort = defineModel<ListTableSort | null>({ default: null })

const { t } = useI18n()
const menuLabel = computed(() => props.label || t('components.sort'))
const active = computed(() => Boolean(sort.value))

function directionLabel(kind: ListTableSortKind, dir: 'asc' | 'desc') {
  if (kind === 'date') return dir === 'asc' ? t('components.sortOldest') : t('components.sortNewest')
  if (kind === 'number') return dir === 'asc' ? t('components.sortSmallest') : t('components.sortLargest')
  return dir === 'asc' ? t('components.sortAsc') : t('components.sortDesc')
}

function select(option: ListTableSortOption, dir: 'asc' | 'desc') {
  const isActive = sort.value?.key === option.key && sort.value?.dir === dir
  // Clicking the active direction again clears the sort.
  sort.value = isActive ? null : { key: option.key, dir, kind: option.kind }
}

const items = computed<DropdownMenuItem[][]>(() => {
  const groups = props.options.map((option): DropdownMenuItem[] => {
    const direction = (dir: 'asc' | 'desc'): DropdownMenuItem => ({
      label: directionLabel(option.kind, dir),
      type: 'checkbox',
      checked: sort.value?.key === option.key && sort.value?.dir === dir,
      onSelect: () => select(option, dir),
    })
    return [
      { type: 'label', label: option.label },
      direction('asc'),
      direction('desc'),
    ]
  })
  if (active.value) {
    groups.push([{
      label: t('components.sortClear'),
      icon: 'i-lucide-x',
      onSelect: () => { sort.value = null },
    }])
  }
  return groups
})
</script>

<template>
  <UDropdownMenu
    v-if="options.length"
    :items="items"
    :content="{ align: 'end', side: 'bottom' }"
  >
    <UButton
      :color="active ? 'primary' : 'neutral'"
      :variant="active ? 'soft' : 'outline'"
      icon="i-lucide-arrow-up-down"
      size="sm"
      square
      :aria-label="menuLabel"
      :title="menuLabel"
    />
  </UDropdownMenu>
</template>
