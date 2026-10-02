import { defineConfig } from '@playwright/test'

// The container ships a pinned Chromium build that differs from the one this
// Playwright version would download, so point at it explicitly.
const executablePath = process.env.PW_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    launchOptions: { executablePath },
    locale: 'ar',
  },
  webServer: [
    { command: 'npm run server', url: 'http://localhost:1234', reuseExistingServer: true, timeout: 30_000 },
    { command: 'npm run dev', url: 'http://localhost:5173', reuseExistingServer: true, timeout: 60_000 },
  ],
})
