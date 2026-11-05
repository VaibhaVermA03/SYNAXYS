import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RepositoriesPage from './RepositoriesPage'
import { mockFetch, renderApp } from '../../test/utils'

afterEach(() => vi.unstubAllGlobals())
const repo = (o) => ({ id: 1, full_name: 'alice/app', default_branch: 'main', is_private: false, language: 'Python', html_url: null,
  is_enabled: false, is_demo: false, role: 'owner', index_status: 'not_indexed', last_indexed_at: null, index_error: null, ...o })
const page = (items) => ({ items, total: items.length, page: 1, page_size: 20 })

function setup(extra = () => null, items = [repo({}), repo({ id: 2, full_name: 'org/locked', role: 'member' }), repo({ id: 3, full_name: 'alice/live', is_enabled: true, index_error: 'Pinecone timeout' })]) {
  return mockFetch((url, method) => extra(url, method)
    || (url.startsWith('/api/v1/github/repositories') && method === 'GET' ? { body: page(items) } : null)
    || (url.endsWith('/github/installations') ? { body: { items: [], install_url: 'https://github.com/apps/x/installations/new' } } : null))
}
const ui = <RepositoriesPage />

describe('RepositoriesPage', () => {
  it('lists repositories with state, index errors and install link', async () => {
    setup(); renderApp(ui, { withAuth: false })
    expect(await screen.findByText('alice/app')).toBeInTheDocument()
    expect(screen.getByText(/Pinecone timeout/)).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /install github app/i })).toBeInTheDocument()
  })

  it('disables connect for non-admin members', async () => {
    setup(); renderApp(ui, { withAuth: false })
    await screen.findByText('org/locked')
    const buttons = screen.getAllByRole('button', { name: 'Connect' })
    expect(buttons[0]).toBeEnabled(); expect(buttons[1]).toBeDisabled()
  })

  it('connects a repository through the API', async () => {
    const f = setup((url, m) => (m === 'POST' && url.endsWith('/1/connect') ? { body: repo({ is_enabled: true }) } : null))
    renderApp(ui, { withAuth: false }); await screen.findByText('alice/app')
    await userEvent.click(screen.getAllByRole('button', { name: 'Connect' })[0])
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u.endsWith('/1/connect') && i.method === 'POST')).toBe(true))
    expect(await screen.findByText(/Reviewing enabled for alice\/app/)).toBeInTheDocument()
  })

  it('requires confirmation before disconnecting', async () => {
    const f = setup((url, m) => (m === 'DELETE' ? { body: repo({ id: 3, full_name: 'alice/live' }) } : null))
    renderApp(ui, { withAuth: false }); await screen.findByText('alice/live')
    await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }))
    expect(screen.getByRole('dialog')).toHaveTextContent(/delete its indexed code search data/i)
    expect(f.mock.calls.some(([, i]) => i.method === 'DELETE')).toBe(false)      // nothing happens before confirming
    await userEvent.click(screen.getAllByRole('button', { name: 'Disconnect' }).at(-1))
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u.endsWith('/3/disconnect') && i.method === 'DELETE')).toBe(true))
  })

  it('tells the user to sign in again when GitHub credentials expired', async () => {
    setup((url, m) => (m === 'POST' && url.endsWith('/sync') ? { status: 409, body: { error: { code: 'github_reauth_required', message: 'x' } } } : null))
    renderApp(ui, { withAuth: false }); await screen.findByText('alice/app')
    await userEvent.click(screen.getByRole('button', { name: /sync from github/i }))
    expect(await screen.findByText(/sign in with github again/i)).toBeInTheDocument()
  })

  it('shows empty and error states', async () => {
    setup(() => null, []); renderApp(ui, { withAuth: false })
    expect(await screen.findByText(/no repositories yet/i)).toBeInTheDocument()
    vi.unstubAllGlobals()
    mockFetch((url) => (url.includes('/github/repositories') ? { status: 500, body: { error: { code: 'internal_error', message: 'x' } } } : { body: { items: [] } }))
    renderApp(ui, { withAuth: false })
    expect((await screen.findAllByRole('alert')).length).toBeGreaterThan(0)
  })
})

describe('RepositoriesPage — indexing', () => {
  const status = (o = {}) => ({ status: 'indexing', available: true, unavailable_reason: null, backend: 'pinecone', indexed_files: 0, error: null,
    job: { id: 1, status: 'indexing', files_total: 40, files_indexed: 10, chunks_upserted: 55, created_at: '' }, ...o })

  it('starts indexing for admins only and tells the user when it is queued', async () => {
    const f = setup((url, m) => (m === 'POST' && url.endsWith('/3/index') ? { status: 202, body: status({ status: 'queued' }) } : url.endsWith('/index-status') ? { body: status({ status: 'queued' }) } : null))
    renderApp(ui, { withAuth: false }); await screen.findByText('alice/live')
    const btns = screen.getAllByRole('button', { name: /index code|re-index|retry indexing/i })
    expect(btns).toHaveLength(1)                                                   // only the connected repo (alice/live) is offered indexing
    await userEvent.click(btns[0])
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u.endsWith('/3/index') && i.method === 'POST')).toBe(true))
    expect(await screen.findByText(/indexing queued/i)).toBeInTheDocument()
  })

  it('shows real progress counts and an accessible progress bar while indexing', async () => {
    setup((url) => (url.endsWith('/index-status') ? { body: status() } : null), [repo({ id: 3, full_name: 'alice/live', is_enabled: true, index_status: 'indexing' })])
    renderApp(ui, { withAuth: false })
    expect(await screen.findByText(/Indexing: 10 of 40 files · 55 chunks/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: /indexing progress/i })).toHaveAttribute('aria-valuenow', '10')
    expect(screen.queryByRole('button', { name: /index code|re-index/i })).not.toBeInTheDocument()   // no double-start while running
  })

  it('surfaces indexing failures and offers a retry; configuration problems come back as clear errors', async () => {
    const f = setup((url, m) => (m === 'POST' && url.endsWith('/index') ? { status: 503, body: { error: { code: 'pinecone_not_configured', message: 'Pinecone is not configured. Set PINECONE_API_KEY and PINECONE_INDEX_NAME.' } } }
      : url.endsWith('/index-status') ? { body: status({ status: 'failed', error: 'Pinecone timeout', job: null }) } : null),
      [repo({ id: 3, full_name: 'alice/live', is_enabled: true, index_status: 'failed', index_error: 'Pinecone timeout' })])
    renderApp(ui, { withAuth: false })
    expect(await screen.findByText(/Indexing failed: Pinecone timeout/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /retry indexing/i }))
    expect(await screen.findByText(/PINECONE_API_KEY/)).toBeInTheDocument()
    expect(f).toBeDefined()
  })
})
