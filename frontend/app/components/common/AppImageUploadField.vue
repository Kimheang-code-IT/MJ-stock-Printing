<script setup lang="ts">
import { ApiEndpoints } from '~/utils/constants/api-endpoints'
import { mediaObjectUrl } from '~/utils/security/url'

const model = defineModel<string | undefined>({ default: undefined })

const props = withDefaults(defineProps<{
  label?: string
  labelKey?: string
  help?: string
  helpKey?: string
  accept?: string
  maxSizeMb?: number
  disabled?: boolean
  /** Compact layout for side-by-side placement next to form fields. */
  compact?: boolean
  /** Storage folder used by POST /images/upload. */
  folder?: string
}>(), {
  accept: SAFE_RASTER_IMAGE_ACCEPT,
  maxSizeMb: 2,
  disabled: false,
  compact: false,
  folder: 'general',
})

const { t, te } = useI18n()
const toast = useToast()
const api = useApi()
const inputRef = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const uploading = ref(false)
const localPreview = ref<string | null>(null)

/**
 * Preview source. While uploading we show the just-picked file; otherwise the
 * stored object key (or URL/data URL) is resolved to a same-origin media URL.
 */
const previewSource = computed(() => {
  if (localPreview.value) return localPreview.value
  return safeImageSource(mediaObjectUrl(model.value)) || sameOriginMediaUrl(model.value)
})

function sameOriginMediaUrl(value: unknown): string | null {
  const url = mediaObjectUrl(value)
  return url && !/^(data:|blob:|https?:)/i.test(url) ? url : null
}

const labelText = computed(() => {
  if (props.label) return props.label
  if (props.labelKey && te(props.labelKey)) return t(props.labelKey)
  return t('core.common.image')
})

const helpText = computed(() => {
  if (props.help) return props.help
  if (props.helpKey && te(props.helpKey)) return t(props.helpKey)
  return t('core.common.imageHelp', { size: props.maxSizeMb })
})

function openPicker() {
  if (props.disabled || uploading.value) return
  inputRef.value?.click()
}

function clear() {
  localPreview.value = null
  model.value = undefined
}

async function uploadFile(file: File) {
  const form = new FormData()
  form.append('file', file)
  form.append('folder', props.folder)
  const response = await api.post<unknown>(ApiEndpoints.IMAGE_UPLOAD, form as unknown as Record<string, unknown>)
  const payload = response && typeof response === 'object' && 'data' in response
    ? (response as { data?: { objectName?: string } }).data
    : undefined
  const objectName = payload?.objectName
  if (!objectName) throw new Error('missing object name')
  return String(objectName)
}

async function readFile(file: File) {
  if (!SAFE_RASTER_IMAGE_TYPES.includes(file.type as (typeof SAFE_RASTER_IMAGE_TYPES)[number])) {
    toast.add({ title: t('core.common.imageInvalidType'), color: 'error' })
    return
  }
  if (!isSafeRasterImage(file, props.maxSizeMb)) {
    toast.add({ title: t('core.common.imageTooLarge', { size: props.maxSizeMb }), color: 'error' })
    return
  }

  uploading.value = true
  try {
    // Instant local preview while the upload is in flight.
    localPreview.value = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result || ''))
      reader.onerror = () => reject(new Error('read failed'))
      reader.readAsDataURL(file)
    })
    model.value = await uploadFile(file)
    localPreview.value = null
  }
  catch {
    localPreview.value = null
    toast.add({ title: t('core.common.imageUploadFailed'), color: 'error' })
  }
  finally {
    uploading.value = false
  }
}

function onInputChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void readFile(file)
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragOver.value = false
  if (props.disabled || uploading.value) return
  const file = event.dataTransfer?.files?.[0]
  if (file) void readFile(file)
}
</script>

<template>
  <UFormField :label="labelText" :help="helpText">
    <div
      class="relative flex cursor-pointer flex-col items-center justify-center gap-2 rounded-sm border border-dashed border-default bg-elevated/40 transition"
      :class="[
        props.compact ? 'min-h-20 p-3' : 'min-h-28 p-4',
        dragOver ? 'border-primary bg-primary/5' : '',
        disabled ? 'pointer-events-none opacity-60' : 'hover:border-primary/50',
      ]"
      @click="openPicker"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
    >
      <template v-if="uploading">
        <UIcon name="i-lucide-loader-circle" class="size-6 animate-spin text-primary" />
      </template>
      <template v-else-if="model">
        <img
v-if="previewSource"
:src="previewSource"
alt=""
:class="props.compact ? 'max-h-16' : 'max-h-24'"
class="max-w-full object-contain"
referrerpolicy="no-referrer">
        <div class="flex gap-2">
          <UButton
size="xs"
color="neutral"
variant="soft"
@click.stop="openPicker">
            {{ t('core.common.replace') }}
          </UButton>
          <UButton
size="xs"
color="error"
variant="ghost"
@click.stop="clear">
            {{ t('core.common.remove') }}
          </UButton>
        </div>
      </template>
      <template v-else>
        <div
          class="grid place-items-center rounded-sm bg-primary/10 ring ring-primary/20"
          :class="props.compact ? 'size-9' : 'size-12'"
        >
          <UIcon name="i-lucide-image-up" :class="props.compact ? 'size-4' : 'size-6'" class="text-primary" />
        </div>
        <p class="font-medium text-highlighted" :class="props.compact ? 'text-xs' : 'text-sm'">
          {{ t('core.common.dropImage') }}
        </p>
      </template>
    </div>
    <input
      ref="inputRef"
      type="file"
      class="hidden"
      :accept="accept"
      :disabled="disabled || uploading"
      @change="onInputChange"
    >
  </UFormField>
</template>
