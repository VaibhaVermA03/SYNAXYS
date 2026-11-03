import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PullRequestsPage from './PullRequestsPage'
import { mockFetch, renderApp, selectOption } from '../../test/utils'

afterEach(() => vi.unstubAllGlobals())
const pr = (o = {}) => ({ id: 1, repository_id: 5, repository: 'alice/app', number: 3, title: 'Add lookup', author: 'bob', state: 'open', base_branch: 'main', head_branch: 'feat',
  html_url: null, updated_at: '2026-01-01T00:00:00Z', is_demo: false, review: { id: 1, status: 'completed', trigger: 'webhook', findings: 2, by_severity: { critical: 0, high: 1, medium: 1, low: 0, info: 0 }, created_at: '', head_sha: 'abc', is_demo: false }, ...o })
const handler = (items) => (url) => (url.startsWith('/api/v1/pull-requests') ? { body: { items, total: items.length, page: 1, page_size: 20 } }
  : url.startsWith('/api/v1/github/repositories') ? { body: { items: [{ id: 5, full_name: 'alice/app' }], total: 1, page: 1, page_size: 100 } } : null)

describe('PullRequestsPage', () => {
  it('shows PR metadata, review progress and severity counts', async () => {
    mockFetch(handler([pr(), pr({ id: 2, number: 4, title: 'Fix', state: 'merged', review: null, is_demo: true })]))
    renderApp(<PullRequestsPage />, { withAuth: false })
    expect(await screen.findByText('Add lookup')).toBeInTheDocument()
    expect(screen.getByText('1 high')).toBeInTheDocument()
    expect(screen.getByText('Not reviewed')).toBeInTheDocument()
    expect(screen.getByText('Demo')).toBeInTheDocument()
  })

  it('sends filters to the API and resets to page 1', async () => {
    const f = mockFetch(handler([pr()]))
    renderApp(<PullRequestsPage />, { withAuth: false }); await screen.findByText('Add lookup')
    await selectOption(userEvent, 'State', 'Merged')
    await selectOption(userEvent, 'Review status', 'Failed')
    await waitFor(() => expect(f.mock.calls.some(([u]) => u.includes('state=merged') && u.includes('review_status=failed') && u.includes('page=1'))).toBe(true))
  })

  it('shows filtered-empty, first-run-empty and error states', async () => {
    mockFetch(handler([])); renderApp(<PullRequestsPage />, { withAuth: false })
    expect(await screen.findByText(/no pull requests tracked yet/i)).toBeInTheDocument()
    await selectOption(userEvent, 'State', 'Open')
    expect(await screen.findByText(/no pull requests match/i)).toBeInTheDocument()
    vi.unstubAllGlobals()
    mockFetch((u) => (u.startsWith('/api/v1/pull-requests') ? { status: 500, body: { error: { code: 'internal_error', message: 'x' } } } : { body: { items: [] } }))
    renderApp(<PullRequestsPage />, { withAuth: false })
    expect((await screen.findAllByRole('alert')).length).toBeGreaterThan(0)
  })
})
