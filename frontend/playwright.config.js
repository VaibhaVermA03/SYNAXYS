import { defineConfig, devices } from '@playwright/test'

// Mocked-API e2e (default): the browser runs the real frontend; /api is intercepted per test, so no GitHub/OpenAI/Pinecone
// and no real accounts are ever used. Set E2E_BACKEND=1 to also run e2e/demo-backend.spec.js against a real local backend.
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://localhost:5173', trace: 'on-first-retry' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: { command: 'npm run dev -- --host localhost', url: 'http://localhost:5173', reuseExistingServer: !process.env.CI, timeout: 60_000 },
})
