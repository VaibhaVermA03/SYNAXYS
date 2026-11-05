import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import ReviewDetailPage from './ReviewDetailPage'
import { mockFetch, renderApp } from '../../test/utils'

afterEach(() => vi.unstubAllGlobals())
const finding = (o) => ({ id: 1, category: 'security', severity: 'high', title: 'SQL injection', explanation: 'x', evidence: 'ev', path: 'a.py', start_line: 1, end_line: 1, remediation: 'fix', patch: null,
  confidence: 0.55, confidence_label: 'medium', inline_possible: false, status: 'open', comment: { id: 1, state: 'draft', body: 'b', edited: false }, ...o })
const review = (o = {}) => ({ id: 3, status: 'completed', trigger: 'webhook', findings: 1, by_severity: { critical: 0, high: 1, medium: 0, low: 0, info: 0 }, created_at: '2026-01-01T00:00:00Z', finished_at: null,
  duration_ms: 1200, error: null, is_demo: false, head_sha: 'abcdef123', repository: 'alice/app', pr_id: 9, pr_number: 4, pr_title: 'T', summary: 'Summary text', model: 'm', ai_generated: true,
  by_category: { security: 1 }, findings_list: [finding({ inline_possible: false })], require_approval: true, auto_publish: false, can_retry: false,
  can_manage: false, approved_comments: 0, publishable: false, publish_blocker: null, ...o })
const route = (f) => (u, m) => f(u, m) || (u.includes('/posting-attempts') ? { body: [] } : null)
const ui = <Routes><Route path="/app/reviews/:reviewId" element={<ReviewDetailPage />} /></Routes>

describe('ReviewDetailPage', () => {
  it('labels findings as AI suggestions with confidence, evidence and summary-only status', async () => {
    mockFetch(() => ({ body: review() })); renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    expect(await screen.findByText('SQL injection')).toBeInTheDocument()
    expect(screen.getByText(/AI suggestion/)).toBeInTheDocument()
    expect(screen.getByText(/Confidence: medium \(55%\)/)).toBeInTheDocument()
    expect(screen.getByText('ev')).toBeInTheDocument()
    expect(screen.getByText(/summary only/i)).toBeInTheDocument()
    expect(screen.getByText(/never approves or requests changes/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /publish/i })).not.toBeInTheDocument()   // read-only users get no controls
    expect(screen.getByText(/only repository admins/i)).toBeInTheDocument()
  })

  it('offers retry for failed reviews and calls the API', async () => {
    const f = mockFetch((u, m) => (m === 'POST' ? { status: 202, body: review({ status: 'queued' }) } : { body: review({ status: 'failed', error: 'OpenAI timeout', can_retry: true, findings_list: [] }) }))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    expect(await screen.findByRole('alert')).toHaveTextContent(/OpenAI timeout/)
    await userEvent.click(screen.getByRole('button', { name: /retry review/i }))
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u.endsWith('/reviews/3/retry') && i.method === 'POST')).toBe(true))
  })

  it('says so when no actionable issue was found, and marks demo fixtures', async () => {
    mockFetch(() => ({ body: review({ findings_list: [], by_category: {}, is_demo: true, findings: 0, by_severity: {} }) }))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    expect(await screen.findByText(/no actionable findings/i)).toBeInTheDocument()
    expect(screen.getByText(/no AI was run/i)).toBeInTheDocument()
  })

  it('shows not-found and in-progress states', async () => {
    mockFetch(() => ({ status: 404, body: { error: { code: 'not_found', message: 'Review not found' } } }))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    expect(await screen.findByText(/review not found/i)).toBeInTheDocument()
  })
})


describe('ReviewDetailPage — approval and publishing', () => {
  const admin = (o = {}) => review({ can_manage: true, ...o })
  const withComment = (state, o = {}) => ({ findings_list: [finding({ inline_possible: true, comment: { id: 11, state, body: 'Proposed body text', edited: false } })], ...o })
  const setup = (rv, extra = () => null) => mockFetch(route((u, m) => extra(u, m) || (u.endsWith('/reviews/3') && m === 'GET' ? { body: rv } : null)))
  const calls = (f, method, suffix) => f.mock.calls.filter(([u, i]) => i.method === method && u.endsWith(suffix))

  it('shows the proposed comment text and its state; drafts can be approved individually', async () => {
    const f = setup(admin(withComment('draft')), (u, m) => (m === 'POST' && u.endsWith('/approve') ? { body: { approved: 1 } } : null))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    expect(await screen.findByText('Proposed body text')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(calls(f, 'POST', '/reviews/3/approve')).toHaveLength(1))
    expect(JSON.parse(calls(f, 'POST', '/reviews/3/approve')[0][1].body)).toEqual({ comment_ids: [11] })
  })

  it('approve-all sends no ids; publishing requires an explicit confirmation and explains the effect', async () => {
    const f = setup(admin({ ...withComment('approved'), approved_comments: 1, publishable: true }), (u, m) => (m === 'POST' && u.endsWith('/publish') ? { body: { posted: 1, skipped_existing: 0, failed: 0, github_review_id: 5 } } : null))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: /publish 1 approved comment/i }))
    expect(screen.getByRole('dialog')).toHaveTextContent(/comment-only review.*visible to everyone/i)
    expect(calls(f, 'POST', '/publish')).toHaveLength(0)                              // nothing is posted before confirming
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(calls(f, 'POST', '/reviews/3/publish')).toHaveLength(1))
    expect(await screen.findByText(/Published 1 comment\(s\) to GitHub/)).toBeInTheDocument()
  })

  it('cancelling the confirmation posts nothing', async () => {
    const f = setup(admin({ ...withComment('approved'), approved_comments: 1, publishable: true }))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: /publish 1 approved comment/i }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(calls(f, 'POST', '/publish')).toHaveLength(0)
  })

  it('stale reviews cannot be published and say why', async () => {
    setup(admin({ ...withComment('approved'), approved_comments: 1, publishable: false, publish_blocker: 'review_stale' }))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    expect(await screen.findByText(/pull request changed after this review/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /publish/i })).not.toBeInTheDocument()
  })

  it('demo reviews and non-admins get no approve/publish controls', async () => {
    setup(review({ ...withComment('draft'), is_demo: true, can_manage: false }))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await screen.findByText('Proposed body text')
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument()
  })

  it('editing saves through the API, warns that re-approval is needed, and shows server validation errors', async () => {
    const f = setup(admin(withComment('approved')), (u, m) => (m === 'PATCH' ? { status: 422, body: { error: { code: 'validation_error', message: 'x', fields: [{ loc: ['body'], msg: 'Comment appears to contain a secret' }] } } } : null))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    expect(screen.getByText(/must be approved again/i)).toBeInTheDocument()
    const box = screen.getByLabelText('Comment text'); await userEvent.clear(box); await userEvent.type(box, 'new text')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/contain a secret/i)).toBeInTheDocument()
    expect(JSON.parse(calls(f, 'PATCH', '/comments/11')[0][1].body)).toEqual({ body: 'new text' })
  })

  it('published comments are read-only and GitHub failures surface as errors', async () => {
    setup(admin(withComment('published')))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await screen.findByText('Proposed body text')
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    vi.unstubAllGlobals()
    setup(admin({ ...withComment('approved'), approved_comments: 1, publishable: true }), (u, m) => (m === 'POST' && u.endsWith('/publish') ? { status: 502, body: { error: { code: 'github_api_error', message: 'x' } } } : null))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    await userEvent.click((await screen.findAllByRole('button', { name: /publish 1 approved comment/i })).at(-1))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Publish' }))
    expect(await screen.findByText(/server had a problem/i)).toBeInTheDocument()
  })

  it('shows the publishing history', async () => {
    mockFetch((u) => (u.includes('/posting-attempts') ? { body: [{ id: 1, comment_id: 11, status: 'success', http_status: 200, error: null, actor: 'alice', created_at: '2026-01-01T00:00:00Z' }] } : { body: admin(withComment('published')) }))
    renderApp(ui, { route: '/app/reviews/3', withAuth: false })
    expect(await screen.findByText('Publishing history')).toBeInTheDocument()
    expect(screen.getByText(/alice · HTTP 200/)).toBeInTheDocument()
  })
})
