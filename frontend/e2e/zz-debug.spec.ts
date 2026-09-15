import { test } from '@playwright/test'

const token = process.env.DEBUG_TOKEN || ''

test('debug detail image preview', async ({ page }) => {
  await page.addInitScript((tok: string) => {
    sessionStorage.setItem('stockpos:auth:access-token', tok)
    sessionStorage.setItem('stockpos:auth:refresh-token', tok)
    const user = {
      id: '78e2688f-2bf2-4dc1-b87c-9846d52c9857',
      email: 'admin@gmail.com',
      fullName: 'System Administrator',
      effectivePermissions: ['ALL_PAGES'],
    }
    localStorage.setItem('stockpos:auth:user', JSON.stringify(user))
    document.cookie = `auth_user=${encodeURIComponent(JSON.stringify(user))}; path=/`
  }, token)
  await page.goto('/stock/products/5d14d4f9-185f-4d65-95d8-feddaf218bfb')
  await page.waitForTimeout(6000)
  const img = await page.locator('img[src*="/api/v1/images/"]').first().getAttribute('src').catch(() => null)
  console.log('DETAIL_IMG', img)
  await page.screenshot({ path: 'e2e/debug-detail.png', fullPage: true })
})
