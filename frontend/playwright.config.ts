import { existsSync } from 'node:fs'

import { defineConfig } from '@playwright/test'

// Local sessions ship a pinned Chromium; CI installs Playwright's own browser.
const localChromium = '/opt/pw-browsers/chromium'
const executablePath = process.env.PW_CHROMIUM_PATH ?? (existsSync(localChromium) ? localChromium : undefined)

// The same development secrets Django uses by default (config/settings/development.py).
const collabSecrets = {
  COLLAB_TOKEN_SECRET: process.env.COLLAB_TOKEN_SECRET ?? 'dev-only-collab-token-secret-change-me',
  COLLAB_SERVICE_SECRET: process.env.COLLAB_SERVICE_SECRET ?? 'dev-only-collab-service-secret-change-me',
}

const backendEnv = {
  ...collabSecrets,
  DJANGO_SETTINGS_MODULE: 'config.settings.development',
  DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgres://harak:harak@127.0.0.1:54329/harak',
  REDIS_URL: process.env.E2E_REDIS_URL ?? 'redis://127.0.0.1:6380/2',
  HARAK_ALLOW_SEED: '1',
  LOGIN_THROTTLE_RATE: '1000/minute',
  LOG_LEVEL: 'WARNING',
}

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    launchOptions: executablePath ? { executablePath } : {},
  },
  webServer: [
    {
      command: 'uv run python manage.py migrate --noinput && uv run python manage.py seed_e2e && uv run python manage.py runserver 127.0.0.1:8000 --noreload',
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/health/',
      env: backendEnv,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: 'npm run start -w collab',
      cwd: '..',
      url: 'http://127.0.0.1:1234/health',
      env: { ...collabSecrets, PORT: '1234', DJANGO_INTERNAL_URL: 'http://127.0.0.1:8000' },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
