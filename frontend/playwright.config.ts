import { defineConfig, devices } from '@playwright/test'

/**
 * Critical browser flows against the **real API** (never mock mode).
 *
 * Run the Docker stack first (frontend serves the built SPA on :80 and
 * proxies `/api` to the API), then:
 *   pnpm --dir frontend exec playwright install chromium
 *   E2E_BASE_URL=http://localhost:80 pnpm --dir frontend e2e
 *
 * Override credentials with E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD (the seed
 * defaults are admin@gmail.com / 123456 in development).
 */
const baseURL = process.env.E2E_BASE_URL || 'http://localhost:80'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})
