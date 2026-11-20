import { defineConfig } from '@playwright/test'

/**
 * E2E runs against a REAL backend (FastAPI + database + trained model) and the real Vite dev server.
 * Start the backend first (CI does this; locally: see docs/TESTING.md). E2E_BACKEND_URL overrides the API address.
 */
const backend = process.env.E2E_BACKEND_URL ?? 'http://127.0.0.1:8000'
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5173',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
    env: { VITE_BACKEND_URL: backend },
  },
})
