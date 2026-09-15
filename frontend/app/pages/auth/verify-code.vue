<script setup lang="ts">
import { useAuth } from '~/composables/auth/useAuth'
import { usePageSeo } from '~/composables/usePageSeo'
import {
  getPasswordResetSession,
  markPasswordResetVerified,
  setPasswordResetLinkCode,
} from '~/utils/auth/password-reset'
import { useClipboard } from '@vueuse/core'

definePageMeta({
  layout: 'auth',
})

const { t } = useI18n()
const router = useRouter()
const toast = useToast()
const { resendPasswordResetCode, verifyPasswordResetCode } = useAuth()
const { copy } = useClipboard()

const verifying = ref(false)
const resending = ref(false)
const code = ref<string[]>(['', '', '', '', '', ''])
const session = ref(getPasswordResetSession())

const linkCode = computed(() => String(session.value?.linkCode || ''))

usePageSeo({
  title: () => t('pages.forgetPassword.verifyTitle'),
  description: () => t('pages.forgetPassword.verifyDesc'),
  robots: 'noindex, nofollow',
})

onMounted(() => {
  session.value = getPasswordResetSession()
  if (!session.value?.email) {
    void router.replace('/auth/forgot-password')
  }
})

const codeComplete = computed(() =>
  code.value.every(digit => digit && digit.length === 1),
)

const codeValue = computed(() => code.value.join(''))

async function onVerifyCode() {
  if (!codeComplete.value || verifying.value || !session.value?.email) return
  verifying.value = true
  try {
    await verifyPasswordResetCode(session.value.email, codeValue.value)
      .then((result) => {
        markPasswordResetVerified(String(result.data?.resetToken || ''))
      })
    toast.add({
      title: t('pages.forgetPassword.codeVerified'),
      description: t('pages.forgetPassword.codeVerifiedDesc'),
      color: 'success',
    })
    await router.push('/auth/reset-password')
  }
  catch {
    toast.add({
      title: t('pages.forgetPassword.codeInvalid'),
      description: t('pages.forgetPassword.codeInvalidDesc'),
      color: 'error',
    })
  }
  finally {
    verifying.value = false
  }
}

async function onResendCode() {
  if (resending.value || !session.value?.email) return
  resending.value = true
  try {
    const result = await resendPasswordResetCode(session.value.email)
    const start = result.data
    if (start?.channel === 'telegram_link') {
      setPasswordResetLinkCode(start.linkCode)
      session.value = getPasswordResetSession()
      toast.add({
        title: t('pages.forgetPassword.linkRequiredTitle'),
        description: t('pages.forgetPassword.linkRequiredDesc'),
        color: 'success',
      })
    }
    else {
      code.value = ['', '', '', '', '', '']
      toast.add({
        title: t('pages.forgetPassword.codeResent'),
        color: 'success',
      })
    }
  }
  catch {
    toast.add({
      title: t('pages.forgetPassword.codeResendFailed'),
      color: 'error',
    })
  }
  finally {
    resending.value = false
  }
}

async function onCopyLinkCode() {
  await copy(linkCode.value)
  toast.add({ title: t('pages.forgetPassword.linkCodeCopied'), color: 'success' })
}
</script>

<template>
  <div class="flex w-full flex-col items-center justify-center">
    <div class="mb-6 flex flex-col items-center gap-3">
      <div class="flex size-28 items-center justify-center overflow-hidden">
        <LayoutAppBrandLogo img-class="size-28 object-contain" />
      </div>
      <h2 class="text-center text-2xl font-normal">
        {{ t('pages.forgetPassword.verifyTitle') }}
      </h2>
      <p class="text-center text-sm text-muted">
        {{ t('pages.forgetPassword.verifyDesc') }}
      </p>
    </div>

    <div
      v-if="linkCode"
      class="mb-5 w-full rounded-lg border border-primary/40 bg-primary/10 p-4 text-sm"
    >
      <p class="font-medium text-highlighted">
        {{ t('pages.forgetPassword.linkRequiredTitle') }}
      </p>
      <p class="mt-1 text-muted">
        {{ t('pages.forgetPassword.linkStep1') }}
      </p>
      <div class="mt-2 flex items-center justify-center gap-2">
        <code class="rounded bg-elevated px-3 py-1 text-base font-semibold tracking-widest">/link {{ linkCode }}</code>
        <UButton
          variant="ghost"
          color="neutral"
          size="xs"
          icon="i-lucide-copy"
          :aria-label="t('pages.forgetPassword.copyLinkCode')"
          @click="onCopyLinkCode"
        />
      </div>
      <p class="mt-2 text-muted">
        {{ t('pages.forgetPassword.linkStep2') }}
      </p>
    </div>

    <form class="flex w-full flex-col items-center gap-5" @submit.prevent="onVerifyCode">
      <UFormField
        :label="t('pages.forgetPassword.enterCode')"
        class="w-full"
      >
        <UPinInput
          v-model="code"
          :length="6"
          size="xl"
          placeholder="○"
          autofocus
          otp
          required
          :aria-label="t('pages.forgetPassword.enterCode')"
          class="justify-center"
        />
      </UFormField>

      <div class="flex items-center justify-center gap-1">
        <span class="text-sm text-muted">{{ t('pages.forgetPassword.didntGetCode') }}</span>
        <UButton
          variant="link"
          size="sm"
          class="underline"
          :loading="resending"
          :disabled="resending"
          @click="onResendCode"
        >
          {{ t('pages.forgetPassword.resendCode') }}
        </UButton>
      </div>

      <UButton
        type="submit"
        color="primary"
        size="lg"
        class="h-10 w-full justify-center text-base font-normal"
        :loading="verifying"
        :disabled="!codeComplete || verifying"
      >
        {{ t('pages.forgetPassword.verifyCode') }}
      </UButton>
    </form>

    <div class="mt-4 flex w-full flex-col gap-2">
      <UButton
        variant="link"
        size="sm"
        class="w-full justify-center text-muted-foreground underline"
        to="/auth/forgot-password"
      >
        {{ t('pages.forgetPassword.changeEmail') }}
      </UButton>
      <UButton
        variant="link"
        size="sm"
        class="w-full justify-center text-muted-foreground underline"
        to="/auth/login"
      >
        <UIcon name="i-lucide-arrow-left" class="mr-1" />
        {{ t('pages.forgetPassword.backToLogin') }}
      </UButton>
    </div>

    <div class="mt-4 text-center">
      <span class="text-sm font-normal text-muted">{{ $t('settings.aboutCopyright') }}</span>
    </div>
  </div>
</template>
