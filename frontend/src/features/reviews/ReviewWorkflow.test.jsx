import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import ReviewDetailPage from './ReviewDetailPage'
import CodeSearchPage from '../code-search/CodeSearchPage'
import { mockFetch, renderApp } from '../../test/utils'

// Phase 2 (batch 14): finding dismissal, queued-review cancel, GitHub comment deletion, search -> PR link. NOT RUN in the authoring sandbox.
afterEach(() => vi.unstubAllGlobals())
const finding = (o) => ({ id: 1, category: 'security', severity: 'high', title: 'SQL injection', explanation: 'x', evidence: 'ev', path: 'a.py', start_line: 1, end_line: 1, remediation: 'fix', patch: null,
  confidence: 0.55, confidence_label: 'medium', inline_possible: false, status: 'open', comment: null, ...o })
const review = (o = {}) => ({ id: 3, status: 'completed', trigger: 'webhook', findings: 1, by_severity: { critical: 0, high: 1, medium: 0, low: 0, info: 0 }, created_at: '2026-01-01T00:00:00Z', finished_at: null,
  duration_ms: 1200, error: null, is_demo: false, head_sha: 'abcdef123', repository: 'alice/app', pr_id: 9, pr_number: 4, pr_title: 'T', summary: 'S', model: 'm', ai_generated: true,
  by_category: { security: 1 }, findings_list: [finding()], require_approval: true, auto_publish: false, can_retry: false, can_manage: true, approved_comments: 0, publishable: false,
  publish_blocker: null, dismissed_count: 0, can_cancel: false, ...o })
const route = (f) => (u, m) => f(u, m) || (u.includes('/posting-attempts') ? { body: [] } : null)
const ui = <Routes><Route path="/app/reviews/:reviewId" element={<ReviewDetailPage />} /></Routes>
const calls = (f, method, suffix) => f.mock.calls.filter(([u, i]) => i.method === method && u.includes(suffix))

describe('finding dismissal is independent of comments', () => {
  it('dismisses a finding that has NO comment, sending an optional reason/note', async () => {
    const f = mockFetch(route((u, m) => (m === 'POST' && u.endsWith('/findings/1/dismiss') ? { body: { id: 1, status: 'dismissed' } } : { body: review() })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: /dismiss finding/i }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(within(dialog).getByLabelText(/reason/i), 'false_positive')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(calls(f, 'POST', '/findings/1/dismiss')).toHaveLength(1))
    expect(JSON.parse(calls(f, 'POST', '/findings/1/dismiss')[0][1].body)).toEqual({ reason: 'false_positive', note: null })
  })

  it('shows who/when/why for a dismissed finding and offers restore; read-only users get no controls', async () => {
    const dismissed = finding({ status: 'dismissed', dismissed_by: 'alice', dismissed_at: '2026-01-02T00:00:00Z', dismiss_reason: 'false_positive', dismiss_note: 'fixture' })
    const f = mockFetch(route((u, m) => (m === 'POST' && u.endsWith('/restore') ? { body: { id: 1, status: 'open' } } : { body: review({ findings_list: [dismissed], dismissed_count: 1 }) })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    expect(await screen.findByText(/dismissed by alice/i)).toHaveTextContent(/False positive/)
    await userEvent.click(screen.getByRole('button', { name: /restore finding/i }))
    await waitFor(() => expect(calls(f, 'POST', '/findings/1/restore')).toHaveLength(1))
  })

  it('does not show finding actions to people who cannot manage', async () => {
    mockFetch(route(() => ({ body: review({ can_manage: false }) })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await screen.findByText('SQL injection')
    expect(screen.queryByRole('button', { name: /dismiss finding/i })).not.toBeInTheDocument()
  })

  it('the dismissed toggle asks the API for dismissed findings', async () => {
    const f = mockFetch(route(() => ({ body: review({ dismissed_count: 2 }) })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: /show dismissed \(2\)/i }))
    await waitFor(() => expect(f.mock.calls.some(([u]) => u.includes('include_dismissed=true'))).toBe(true))
  })
})

describe('cancel queued review', () => {
  it('offers Cancel only while queued, asks for confirmation, and calls the cancel endpoint', async () => {
    const f = mockFetch(route((u, m) => (m === 'POST' && u.endsWith('/reviews/3/cancel') ? { body: { status: 'cancelled', cancelled_jobs: 1 } } : { body: review({ status: 'queued', can_cancel: true, findings_list: [] }) })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: /cancel review/i }))
    expect(calls(f, 'POST', '/cancel')).toHaveLength(0)                        // nothing happens before the confirmation
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /cancel review/i }))
    await waitFor(() => expect(calls(f, 'POST', '/reviews/3/cancel')).toHaveLength(1))
  })

  it('shows the server answer when a worker already started the review', async () => {
    mockFetch(route((u, m) => (m === 'POST' ? { status: 409, body: { error: { code: 'not_queued', message: 'This review was picked up by a worker a moment ago and can no longer be cancelled.' } } } : { body: review({ status: 'queued', can_cancel: true, findings_list: [] }) })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: /cancel review/i }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /cancel review/i }))
    expect(await screen.findByText(/picked up by a worker/i)).toBeInTheDocument()
  })

  it('does not offer cancel for completed reviews', async () => {
    mockFetch(route(() => ({ body: review() })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await screen.findByText('SQL injection')
    expect(screen.queryByRole('button', { name: /cancel review/i })).not.toBeInTheDocument()
  })
})

describe('delete a published GitHub comment', () => {
  const published = review({ findings_list: [finding({ inline_possible: true, status: 'published', comment: { id: 11, state: 'published', body: 'Posted body', edited: false } })] })
  it('requires confirmation, then calls DELETE; the record stays visible as deleted', async () => {
    let deleted = false
    const f = mockFetch(route((u, m) => (m === 'DELETE' ? (deleted = true, { body: { outcome: 'deleted', state: 'deleted' } })
      : { body: deleted ? review({ findings_list: [finding({ comment: { id: 11, state: 'deleted', body: 'Posted body', edited: false, github_deleted_at: '2026-01-03T00:00:00Z' } })] }) : published })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: /delete from github/i }))
    expect(calls(f, 'DELETE', '/comments/11/github')).toHaveLength(0)
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /delete from github/i }))
    await waitFor(() => expect(calls(f, 'DELETE', '/comments/11/github')).toHaveLength(1))
    expect(await screen.findByText(/deleted from github on/i)).toBeInTheDocument()
    expect(screen.getByText('Posted body')).toBeInTheDocument()
  })

  it('surfaces GitHub permission errors', async () => {
    mockFetch(route((u, m) => (m === 'DELETE' ? { status: 502, body: { error: { code: 'github_permission_denied', message: 'GitHub refused to delete the comment.' } } } : { body: published })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: /delete from github/i }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /delete from github/i }))
    expect(await screen.findByText(/refused to delete/i)).toBeInTheDocument()
  })

  it('is not offered to non-admins', async () => {
    mockFetch(route(() => ({ body: { ...published, can_manage: false } })))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await screen.findByText('Posted body')
    expect(screen.queryByRole('button', { name: /delete from github/i })).not.toBeInTheDocument()
  })
})

describe('search results link to the related pull request', () => {
  const hit = (o = {}) => ({ id: 'a#1', score: 0.7, repository: 'alice/app', repository_id: 1, path: 'app/db.py', start_line: 3, end_line: 9, language: 'python', branch: 'feature-x', commit: 'abcdef123456',
    snippet: 'code', explanation: 'e', github_url: 'https://github.com/alice/app/blob/abcdef123456/app/db.py#L3-L9', pull_request: null, ...o })
  const run = async (h) => {
    mockFetch((u, m) => (u.startsWith('/api/v1/github/repositories') ? { body: { items: [{ id: 1, full_name: 'alice/app', is_enabled: true, index_status: 'indexed', role: 'owner' }], total: 1, page: 1, page_size: 100 } }
      : u.endsWith('/code-search/query') && m === 'POST' ? { body: { results: [h], searched_repositories: ['alice/app'], backend: 'Pinecone', note: null } } : null))
    renderApp(<CodeSearchPage />, { route: '/app/code-search', withAuth: false })
    await userEvent.type(await screen.findByLabelText('Search query'), 'database')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  }
  it('shows repository, branch and a direct pull request link taken from the API', async () => {
    await run(hit({ pull_request: { id: 9, number: 12, title: 'T', state: 'open', html_url: 'https://github.com/alice/app/pull/12', match: 'branch' } }))
    expect(await screen.findByText(/feature-x @ abcdef1/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /PR #12 \(open\)/ })).toHaveAttribute('href', 'https://github.com/alice/app/pull/12')
  })
  it('shows no pull request link when none is related', async () => {
    await run(hit())
    await screen.findByText('app/db.py:3–9')
    expect(screen.queryByRole('link', { name: /PR #/ })).not.toBeInTheDocument()
  })
})
