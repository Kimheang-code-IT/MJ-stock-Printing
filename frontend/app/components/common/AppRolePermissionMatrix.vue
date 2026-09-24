<script setup lang="ts">
import type { AppRolePermissionRow } from '~/types/mj/entities'
import {
  PERMISSION_MATRIX_PAGES,
  allFrontendPermissionCodes,
  flatKeysToPermissionRows,
  isFullAccessRows,
  matrixGroupFor,
  normalizePermissionRows,
  orderedPageActions,
  permissionRowsToFlatKeys,
  type MatrixActionDefinition,
  type MatrixPageDefinition,
} from '~/utils/role/permissions'
import { ApiEndpoints } from '~/utils/constants/api-endpoints'
import type { ApiResponse } from '~/types/mj/common'

const rows = defineModel<AppRolePermissionRow[]>({ default: () => [] })

const props = withDefaults(defineProps<{
  disabled?: boolean
  /** System role (Administrator): every page action stays granted and locked. */
  systemRole?: boolean
}>(), {
  disabled: false,
  systemRole: false,
})

const { t, te } = useI18n()
const api = useApi()

interface CatalogModule {
  module: string
  actions: string[]
  permissions?: string[]
}

/** Live backend catalog (module → allowed actions); empty = fall back to mirror. */
const definitions = ref<CatalogModule[]>([])

function codeFor(module: string, action: string): string {
  // Catalog actions are module-relative, including dotted ones like `debt.pay`
  // → `supplier.debt.pay`. Never treat a dotted action as already fully qualified.
  if (action === module || action.startsWith(`${module}.`)) return action
  return `${module}.${action}`
}

/** Backend permission codes available to assign (live catalog or local mirror). */
const availableCodes = computed<Set<string>>(() => {
  if (!definitions.value.length) return new Set(allFrontendPermissionCodes())
  const codes = new Set<string>()
  for (const definition of definitions.value) {
    if (definition.permissions?.length) {
      for (const permission of definition.permissions) codes.add(permission)
      continue
    }
    for (const action of definition.actions) codes.add(codeFor(definition.module, action))
  }
  return codes
})

/** Catalog codes the page registry does not model yet (forward compatibility). */
function extraPages(): MatrixPageDefinition[] {
  const known = new Set(allFrontendPermissionCodes())
  const byModule = new Map<string, string[]>()
  for (const definition of definitions.value) {
    for (const action of definition.actions) {
      const code = codeFor(definition.module, action)
      if (known.has(code)) continue
      byModule.set(definition.module, [...(byModule.get(definition.module) || []), action])
    }
  }
  return [...byModule.entries()].map(([module, actions]) => ({
    value: module,
    labelKey: '',
    group: matrixGroupFor(module),
    actions: actions.map(action => ({ key: action, permission: codeFor(module, action) })),
  }))
}

/** Page rows limited to the actions the backend actually exposes. */
const pages = computed<MatrixPageDefinition[]>(() => {
  const available = availableCodes.value
  const base = PERMISSION_MATRIX_PAGES
    .map(page => ({
      ...page,
      actions: page.actions.filter(action => available.has(action.permission)),
    }))
    .filter(page => page.actions.length > 0)
  return [...base, ...extraPages()]
})

const allCodes = computed<Set<string>>(() => {
  const codes = new Set<string>()
  for (const page of pages.value) {
    for (const action of page.actions) codes.add(action.permission)
  }
  return codes
})

/** Administrator / ALL_PAGES: every cell is granted and non-editable. */
const lockedFullAccess = computed(() => props.systemRole || isFullAccessRows(rows.value))

/** Single source of truth for every checked cell (shared codes stay in sync). */
const grantedCodes = computed<Set<string>>(() => {
  if (lockedFullAccess.value) return new Set(allCodes.value)
  return new Set(permissionRowsToFlatKeys(rows.value))
})

const grantedCount = computed(() => grantedCodes.value.size)
const totalCount = computed(() => allCodes.value.size)
const matrixLocked = computed(() => props.disabled || lockedFullAccess.value)

function moduleLabel(page: MatrixPageDefinition): string {
  if (page.labelKey && te(page.labelKey)) return t(page.labelKey)
  return page.value.replaceAll('_', ' ').replaceAll('.', ' ')
}

interface DisplayPage extends MatrixPageDefinition {
  label: string
  selected: string[]
  orderedActions: MatrixActionDefinition[]
}

const displayPages = computed<DisplayPage[]>(() =>
  pages.value.map(page => ({
    ...page,
    label: moduleLabel(page),
    orderedActions: orderedPageActions(page),
    selected: page.actions
      .filter(action => grantedCodes.value.has(action.permission))
      .map(action => action.key),
  })),
)

function actionLabel(action: string) {
  const key = `core.rolePermissions.actions.${action}`
  return te(key) ? t(key) : action.replaceAll('_', ' ').replaceAll('.', ' ')
}

function hasAction(page: MatrixPageDefinition, actionKey: string) {
  const action = page.actions.find(item => item.key === actionKey)
  return Boolean(action && grantedCodes.value.has(action.permission))
}

/** Persist a granted-code set back into matrix rows (and thus the role). */
function commitCodes(codes: Iterable<string>) {
  rows.value = normalizePermissionRows(flatKeysToPermissionRows([...new Set(codes)]))
}

/** ERP view dependency: non-view grants View; clearing View clears the page. */
function toggleAction(page: MatrixPageDefinition, actionKey: string, checked: boolean | 'indeterminate') {
  if (matrixLocked.value) return
  const action = page.actions.find(item => item.key === actionKey)
  if (!action) return
  const next = new Set(grantedCodes.value)
  if (checked === true) {
    next.add(action.permission)
    if (actionKey !== 'view') {
      const view = page.actions.find(item => item.key === 'view')
      if (view) next.add(view.permission)
    }
  }
  else if (actionKey === 'view') {
    for (const item of page.actions) next.delete(item.permission)
  }
  else {
    next.delete(action.permission)
  }
  commitCodes(next)
}

function toggleRow(page: MatrixPageDefinition, checked: boolean | 'indeterminate') {
  if (matrixLocked.value) return
  const next = new Set(grantedCodes.value)
  for (const action of page.actions) {
    if (checked === true) next.add(action.permission)
    else next.delete(action.permission)
  }
  commitCodes(next)
}

function toggleAll(checked: boolean) {
  if (matrixLocked.value) return
  commitCodes(checked ? allCodes.value : [])
}

/** Row checkbox state (true / indeterminate / false). */
function rowState(page: DisplayPage): boolean | 'indeterminate' {
  if (!page.actions.length) return false
  if (page.selected.length === 0) return false
  if (page.selected.length === page.actions.length) return true
  return 'indeterminate'
}

/** Header checkbox state across every page row. */
function headerState(): boolean | 'indeterminate' {
  if (!displayPages.value.length) return false
  const total = displayPages.value.reduce((sum, page) => sum + page.actions.length, 0)
  const selected = displayPages.value.reduce((sum, page) => sum + page.selected.length, 0)
  if (selected === 0) return false
  return selected === total ? true : 'indeterminate'
}

function toggleAllVisible(checked: boolean | 'indeterminate') {
  if (matrixLocked.value) return
  toggleAll(checked === true)
}

onMounted(async () => {
  try {
    const response = await api.get<ApiResponse<CatalogModule[]>>(
      ApiEndpoints.PERMISSIONS,
      { suppressErrorToast: true, requestKey: 'permission-catalog' },
    )
    const catalog = Array.isArray(response) ? response : response.data
    definitions.value = (catalog || [])
      .map(group => ({
        module: String(group.module),
        actions: (group.actions || []).map(String),
        permissions: Array.isArray(group.permissions)
          ? group.permissions.map(String)
          : undefined,
      }))
      .filter(group => group.actions.length > 0 || (group.permissions?.length ?? 0) > 0)
  }
  catch {
    // Fall back to the local mirror so role editing still works.
    definitions.value = []
  }
})
</script>

<template>
  <div class="overflow-hidden rounded-sm border border-default">
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-default bg-elevated/70 px-3 py-2.5">
      <div class="min-w-0">
        <p class="text-sm font-semibold text-highlighted">{{ $t('core.rolePermissions.matrixTitle') }}</p>
        <p class="text-xs text-muted">
          {{ $t('core.rolePermissions.grantedCount', { granted: grantedCount, total: totalCount }) }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <UButton
          color="neutral"
          variant="outline"
          size="sm"
          icon="i-lucide-shield-x"
          :disabled="matrixLocked || grantedCount === 0"
          @click="toggleAll(false)"
        >
          {{ $t('core.rolePermissions.clearAll') }}
        </UButton>
        <UButton
          color="error"
          variant="soft"
          size="sm"
          icon="i-lucide-shield-plus"
          :disabled="matrixLocked || grantedCount === totalCount"
          @click="toggleAll(true)"
        >
          {{ $t('core.rolePermissions.grantAll') }}
        </UButton>
      </div>
    </div>

    <div class="max-h-[70vh] overflow-auto">
      <table class="min-w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th
              scope="col"
              class="sticky left-0 top-0 z-30 w-56 min-w-48 border-b border-default bg-elevated px-3 py-2.5 text-left font-semibold text-highlighted"
            >
              <span class="flex items-center gap-2">
                <UCheckbox
                  :model-value="headerState()"
                  :disabled="matrixLocked"
                  :aria-label="$t('core.rolePermissions.toggleAllRows')"
                  @update:model-value="toggleAllVisible"
                />
                {{ $t('core.rolePermissions.documentType') }}
              </span>
            </th>
            <th
              scope="col"
              class="sticky top-0 z-20 border-b border-default bg-elevated px-3 py-2.5 text-left font-semibold text-highlighted"
            >
              {{ $t('core.fields.permissions') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="page in displayPages"
            :key="page.value"
            class="group align-top"
          >
            <th
              scope="row"
              class="sticky left-0 z-10 border-b border-default bg-default px-3 py-3 text-left font-medium text-highlighted group-hover:bg-elevated/60"
            >
              <span class="flex items-start gap-2">
                <UCheckbox
                  class="mt-0.5"
                  :model-value="rowState(page)"
                  :disabled="matrixLocked"
                  :aria-label="$t('core.rolePermissions.toggleRow', { entity: page.label })"
                  @update:model-value="(value) => toggleRow(page, value)"
                />
                <span class="min-w-0 leading-5">{{ page.label }}</span>
              </span>
            </th>
            <td class="border-b border-default px-3 py-3 group-hover:bg-elevated/40">
              <div class="grid grid-cols-1 gap-x-8 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
                <label
                  v-for="action in page.orderedActions"
                  :key="action.key"
                  class="flex min-w-0 items-center gap-2 text-sm text-default"
                  :class="matrixLocked ? 'cursor-default opacity-70' : 'cursor-pointer'"
                >
                  <UCheckbox
                    :model-value="hasAction(page, action.key)"
                    :disabled="matrixLocked"
                    size="sm"
                    :aria-label="`${page.label} — ${actionLabel(action.key)}`"
                    @update:model-value="(value) => toggleAction(page, action.key, value)"
                  />
                  <span class="truncate">{{ actionLabel(action.key) }}</span>
                </label>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <p v-if="!displayPages.length" class="px-3 py-6 text-center text-sm text-muted">
        {{ $t('core.rolePermissions.noResults') }}
      </p>
    </div>

    <div class="border-t border-default bg-muted/30 px-3 py-2 text-xs text-muted">
      {{ systemRole
        ? $t('core.rolePermissions.fullAccessSystemHint')
        : $t('core.rolePermissions.dependencyHint') }}
    </div>
  </div>
</template>
