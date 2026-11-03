import { expect, test } from '@playwright/test'

// Optional: runs against a REAL local backend seeded with demo data.
//   backend:  cd backend && alembic upgrade head && python -m app.db.seed && uvicorn app.main:app --port 8000
//   frontend: (started by Playwright)   run:  E2E_BACKEND=1 npm run e2e
test.skip(!process.env.E2E_BACKEND, 'set E2E_BACKEND=1 with a seeded local backend to run this spec')

test('seeded sample data is clearly labelled and read-only', async ({ page }) => {
  // The login page has no sample-data button. Sign in with the developer API helper (backend needs DEMO_LOGIN_ENABLED=true and `python -m app.db.seed`).
  expect((await page.request.post('/api/v1/auth/demo-login')).status()).toBe(204)
  await page.goto('/app/dashboard')
  await expect(page).toHaveURL(/\/app\/dashboard/)
  await expect(page.getByText(/sample demo data/i)).toBeVisible()
  await page.getByRole('link', { name: 'Pull Requests' }).click()
  await expect(page.getByText('Demo', { exact: true }).first()).toBeVisible()
  await page.getByRole('link', { name: /Add user lookup/ }).click()
  await expect(page.getByText(/read-only sample data/i)).toBeVisible()
  await expect(page.getByRole('article', { name: /high finding/i }).first()).toContainText('AI suggestion')
  await page.getByRole('link', { name: 'Open full review' }).click()
  await expect(page.getByText(/no AI was run/i)).toBeVisible()
  await expect(page.getByRole('button', { name: /publish/i })).toHaveCount(0)             // demo data can never be published
})
