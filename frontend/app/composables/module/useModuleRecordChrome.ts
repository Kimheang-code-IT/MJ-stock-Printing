import type { PersonSummary } from '~/types/stock-pos/common'
import type { AppRecord } from '~/config/admin-seed'
import type { ModuleConfig } from '~/config/modules'

export function useModuleRecordChrome(options: {
  module: ComputedRef<ModuleConfig | undefined>
  isCreate: ComputedRef<boolean>
  recordId: ComputedRef<string>
  model: Ref<AppRecord>
}) {
  const store = useAppDataStore()
  const auth = useAuthStore()
  const { t } = useI18n()

  const currentUser = computed<PersonSummary>(() => ({
    id: String(auth.user?.id || 'me'),
    name: auth.user?.name || 'You',
    email: auth.user?.email,
  }))

  const listTo = computed(() => options.module.value?.path || '/')

  const siblingIds = computed(() => {
    if (!options.module.value) return []
    return store.list(options.module.value.collection).map(row => String(row.id))
  })

  const siblingIndex = computed(() => siblingIds.value.indexOf(options.recordId.value))
  const canNavigatePrevious = computed(() => siblingIndex.value > 0)
  const canNavigateNext = computed(() => siblingIndex.value >= 0 && siblingIndex.value < siblingIds.value.length - 1)

  async function navigatePrevious() {
    const id = siblingIds.value[siblingIndex.value - 1]
    if (id && options.module.value) await navigateTo(`${options.module.value.path}/${id}`)
  }

  async function navigateNext() {
    const id = siblingIds.value[siblingIndex.value + 1]
    if (id && options.module.value) await navigateTo(`${options.module.value.path}/${id}`)
  }

  const metaOwner = computed<PersonSummary>(() => ({
    id: 'owner',
    name: String(options.model.value.createdBy || options.model.value.assignedStaff || currentUser.value.name),
  }))

  function patch(partial: Record<string, unknown>) {
    options.model.value = { ...options.model.value, ...partial }
  }

  function setChromeField(key: string, value: unknown) {
    if (key === 'assignee') {
      const person = (Array.isArray(value) ? value[0] : value) as PersonSummary | null
      patch({
        assignee: person || null,
        assignedStaff: person?.name || '',
      })
      return
    }
    patch({ [key]: value })
  }

  return {
    t,
    currentUser,
    listTo,
    canNavigatePrevious,
    canNavigateNext,
    navigatePrevious,
    navigateNext,
    metaOwner,
    setChromeField,
  }
}
