import { expect, test } from '@playwright/test'
import { installMockApi } from './mockApi'

// Spec §17 e2e journey with a mocked API: auth -> connect repo -> view PR -> run review -> inspect -> approve -> publish -> search.
test('full review journey with mocked GitHub and AI', async ({ page }) => {
  const st = await installMockApi(page)

  // 1. authentication: the real "Continue with GitHub" link; the mocked API answers the OAuth redirect and the callback page completes sign-in
  await page.goto('/app/dashboard')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('button', { name: /sample data|explore|demo/i })).toHaveCount(0)   // no sample-data shortcut exists
  await page.getByRole('link', { name: /continue with github/i }).click()
  await expect(page).toHaveURL(/\/app\/dashboard/)

  // 2. connect a mocked repository and index it
  await page.getByRole('link', { name: 'Repositories', exact: true }).click()
  await expect(page.getByText('alice/shop')).toBeVisible()
  await page.getByRole('button', { name: 'Connect', exact: true }).click()
  await expect(page.getByText('Reviewing enabled for alice/shop.')).toBeVisible()
  await page.getByRole('button', { name: /index code/i }).click()
  await expect(page.getByText('Indexing queued.')).toBeVisible()

  // 3. view the pull request and its diff
  await page.getByRole('link', { name: 'Pull Requests' }).click()
  await page.getByRole('link', { name: 'Add user lookup' }).click()
  await expect(page.getByRole('table', { name: /diff of app\/users.py/i })).toBeVisible()
  await expect(page.getByText('+cur.execute(q)')).toBeVisible()

  // 4. run the (mocked) AI review and inspect findings: labelled as an AI suggestion, never as confirmed
  await page.getByRole('button', { name: /review this pr/i }).click()
  await expect(page.getByText('Review queued.')).toBeVisible()
  const finding = page.getByRole('article', { name: /high finding: SQL injection/i }).first()
  await expect(finding).toBeVisible()
  await expect(finding).toContainText('AI suggestion')
  await expect(finding).toContainText('Confidence: high')

  // 5. approve, then publish only after the confirmation dialog
  await page.getByRole('link', { name: 'Open full review' }).click()
  await expect(page.getByRole('button', { name: /publish/i })).toHaveCount(0)        // nothing publishable before approval
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await page.getByRole('button', { name: /publish 1 approved comment/i }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText(/comment-only review/i)
  expect(st.calls).not.toContain('POST /reviews/3/publish')                           // not posted before confirming
  await dialog.getByRole('button', { name: 'Publish' }).click()

  // 6. verify the mocked publishing result
  await expect(page.getByText(/Published 1 comment\(s\) to GitHub/)).toBeVisible()
  await expect(page.getByText('Publishing history')).toBeVisible()
  expect(st.published).toBe(true)

  // 7. semantic search over the indexed sample codebase
  await page.getByRole('link', { name: 'Codebase Search' }).click()
  await page.getByLabel('Search query').fill('open connection pool')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByText('app/db.py:3–9')).toBeVisible()
  await expect(page.getByText(/strong semantic similarity/)).toBeVisible()
})

test('protected routes redirect to login and sign-out ends the session', async ({ page }) => {
  const st = await installMockApi(page)
  await page.goto('/app/reviews')
  await expect(page).toHaveURL(/\/login/)
  await page.getByRole('link', { name: /continue with github/i }).click()
  await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible()
  await page.getByRole('button', { name: /sign out/i }).click()
  await expect(page).toHaveURL(/\/login/)
  expect(st.signedIn).toBe(false)
})

test('unknown pages show a helpful not-found message and API failures show retryable errors', async ({ page }) => {
  const st = await installMockApi(page); st.signedIn = true
  await page.goto('/app/does-not-exist')
  await expect(page.getByText(/page not found/i)).toBeVisible()
  await page.route('**/api/v1/dashboard', (r) => r.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: { code: 'internal_error', message: 'x' } }) }))
  await page.goto('/app/dashboard')
  await expect(page.getByRole('button', { name: /try again/i })).toBeVisible()
})
