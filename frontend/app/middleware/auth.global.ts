import { useAccessAlert } from '~/composables/common/useAccessAlert'
import { safeInternalPath } from '~/utils/auth/session'
import { resolveApiBase } from '~/utils/api/base-url'
import { ApiEndpoints } from '~/utils/constants/api-endpoints'

const PERMITTED_LANDING_ROUTES = [
  ['/', 'dashboard.view'],
  ['/setup/categories', 'category.view'],
  ['/setup/uoms', 'uom.view'],
  ['/setup/brands', 'brand.view'],
  ['/stock/products', 'stock.view'],
  ['/setup/suppliers', 'supplier.view'],
  ['/pos', 'pos.access'],
  ['/setup/customers', 'customer.view'],
  ['/reports/sales', 'report.sales'],
  ['/administration/users', 'user.manage'],
  ['/administration/settings', 'settings.manage'],
] as const

// Public `GET /auth/setup/status`, cached only once completed (it never flips
// back). Fail-open so a transient API error still shows the login page.
let setupCompletedCache = false

async function isSetupCompleted(): Promise<boolean> {
  if (setupCompletedCache) return true
  try {
    const config = useRuntimeConfig()
    const base = resolveApiBase({
      configured: String(config.public.apiBase || ''),
      requireHttps: import.meta.env.PROD,
    })
    const response = await $fetch<{ data?: { setup_completed?: boolean } }>(
      ApiEndpoints.AUTH_SETUP_STATUS,
      {
        baseURL: base || undefined,
        timeout: Number(config.public.apiTimeoutMs) || 30000,
      },
    )
    const completed = response?.data?.setup_completed !== false
    if (completed) setupCompletedCache = true
    return completed
  }
  catch {
    return true
  }
}

export default defineNuxtRouteMiddleware(async (to, from) => {
  const auth = useAuthStore()
  const { showPermissionDenied } = useAccessAlert()

  if (import.meta.client && auth.user && !auth.hasSessionTokens()) {
    auth.clearSession()
  }

  const publicPaths = [
    '/auth/login',
    '/auth/setup',
    '/auth/forgot-password',
    '/auth/forget-password',
    '/auth/verify-code',
    '/auth/reset-password',
  ]
  const path = to.path.replace(/\/+$/, '') || '/'
  const isPublicPage = publicPaths.includes(path)

  if (!auth.isLoggedIn && !isPublicPage) {
    return navigateTo({
      path: '/auth/login',
      query: { redirect: to.fullPath },
    }, { replace: true })
  }

  // First run (no user yet): the SPA must create the administrator before any
  // sign-in page can be used, and Initial Setup is hidden once completed.
  if (!auth.isLoggedIn && isPublicPage) {
    const completed = await isSetupCompleted()
    if (!completed && path !== '/auth/setup') {
      return navigateTo('/auth/setup', { replace: true })
    }
    if (completed && path === '/auth/setup') {
      return navigateTo('/auth/login', { replace: true })
    }
  }

  if (auth.isLoggedIn && isPublicPage) {
    return navigateTo(safeInternalPath(to.query.redirect) || '/', { replace: true })
  }

  const permission = typeof to.meta.permission === 'string' ? to.meta.permission : ''
  if (auth.isLoggedIn && permission && !auth.canAccessPage(permission)) {
    showPermissionDenied({
      requestedPath: to.fullPath,
      permission,
    })

    // Keep the current authorized page when denial happens during navigation.
    if (from.matched.length && from.path !== to.path) return abortNavigation()

    // A direct URL needs an authorized page underneath the global dialog.
    const landing = PERMITTED_LANDING_ROUTES.find(([, required]) => auth.canAccessPage(required))
    if (landing) return navigateTo(landing[0], { replace: true })

    // An account with no usable page returns to sign-in without creating a denial page.
    auth.clearSession()
    return navigateTo('/auth/login', { replace: true })
  }
})
