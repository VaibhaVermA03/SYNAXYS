import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BranchIndexPanel from '../../components/repositories/BranchIndexPanel'
import CodeSearchPage from '../code-search/CodeSearchPage'
import { mockFetch, renderApp, selectOption } from '../../test/utils'

// Phase 3 (batch 15): branch indexing panel + search branch selector. NOT RUN in the authoring sandbox.
afterEach(() => vi.unstubAllGlobals())
const repo = { id: 1, full_name: 'alice/app', default_branch: 'main', index_status: 'partial' }
const bs = (o) => ({ branch: 'main', is_default: true, status: 'indexed', files_indexed: 10, files_eligible: 10, files_deferred: 0, failed_batches: 0, tree_incomplete: false, error: null, ...o })
const statusBody = (branches) => ({ status: 'partial', available: true, backend: 'pinecone', indexed_files: 10, branch: 'main', branches, job: null })
const calls = (f, method, suffix) => f.mock.calls.filter(([u, i]) => (i.method || 'GET') === method && u.includes(suffix))

describe('BranchIndexPanel', () => {
  it('fetches nothing until it is opened, then lists branches with their state', async () => {
    const f = mockFetch((u) => (u.includes('/index-status') ? { body: statusBody([bs(), bs({ branch: 'dev', is_default: false, status: 'partial', failed_batches: 2, error: '2 batch(es) failed; retry the failed batches.', files_deferred: 7 })]) } : null))
    renderApp(<BranchIndexPanel repository={repo} />, { withAuth: false })
    expect(f).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /branches/i }))
    expect(await screen.findByText('dev')).toBeInTheDocument()
    expect(screen.getByText(/7 eligible files left out by the file limit/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument()
  })

  it('continues a partial branch (only the missing work) via retry-failed', async () => {
    const f = mockFetch((u, m) => (m === 'POST' && u.endsWith('/index/retry-failed') ? { status: 202, body: statusBody([]) }
      : u.includes('/index-status') ? { body: statusBody([bs({ branch: 'dev', is_default: false, status: 'partial', failed_batches: 1, error: 'x' })]) } : null))
    renderApp(<BranchIndexPanel repository={repo} />, { withAuth: false })
    await userEvent.click(screen.getByRole('button', { name: /branches/i }))
    await userEvent.click(await screen.findByRole('button', { name: /continue/i }))
    await waitFor(() => expect(calls(f, 'POST', '/index/retry-failed')).toHaveLength(1))
    expect(JSON.parse(calls(f, 'POST', '/index/retry-failed')[0][1].body)).toEqual({ branch: 'dev' })
  })

  it('indexes another branch chosen from the live GitHub list and confirms before removing one', async () => {
    const f = mockFetch((u, m) => (m === 'POST' && u.endsWith('/index') ? { status: 202, body: statusBody([]) }
      : m === 'DELETE' ? { status: 202, body: { status: 'queued' } }
      : u.includes('/github-branches') ? { body: { default_branch: 'main', branches: ['main', 'dev', 'release'], indexed: ['main', 'dev'], max_extra_branches: 5 } }
      : u.includes('/index-status') ? { body: statusBody([bs(), bs({ branch: 'dev', is_default: false })]) } : null))
    const user = userEvent.setup()
    renderApp(<BranchIndexPanel repository={repo} />, { withAuth: false })
    await user.click(screen.getByRole('button', { name: /branches/i }))
    await user.click(await screen.findByRole('button', { name: /index another branch/i }))
    await selectOption(user, 'Branch to index', 'release')                  // main/dev are already indexed and not offered
    await user.click(screen.getByRole('button', { name: 'Index branch' }))
    await waitFor(() => expect(JSON.parse(calls(f, 'POST', '/index')[0][1].body)).toEqual({ branch: 'release' }))
    await user.click(await screen.findByRole('button', { name: /remove index of dev/i }))
    expect(calls(f, 'DELETE', '/branches/')).toHaveLength(0)                // nothing before the confirmation
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /remove index/i }))
    await waitFor(() => expect(calls(f, 'DELETE', '/branches/dev')).toHaveLength(1))
  })
})

describe('search branch selector', () => {
  const r1 = { id: 1, full_name: 'alice/app', is_enabled: true, index_status: 'indexed', role: 'owner' }
  const setup = (search) => mockFetch((u, m) => (u.startsWith('/api/v1/github/repositories') ? { body: { items: [r1], total: 1, page: 1, page_size: 100 } }
    : u.startsWith('/api/v1/code-search/branches') ? { body: { branches: [{ branch: 'main', repositories: 1, is_default_somewhere: true }, { branch: 'dev', repositories: 1, is_default_somewhere: false }] } }
    : u.endsWith('/code-search/query') && m === 'POST' ? search() : null))
  it('sends the chosen branch and omits it for the default', async () => {
    const f = setup(() => ({ body: { results: [], searched_repositories: ['alice/app'], backend: 'Pinecone', note: null, branch: 'dev' } }))
    const user = userEvent.setup()
    renderApp(<CodeSearchPage />, { route: '/app/code-search', withAuth: false })
    await user.type(await screen.findByLabelText('Search query'), 'database')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(f.mock.calls.some(([u]) => u.endsWith('/code-search/query'))).toBe(true))
    expect(JSON.parse(f.mock.calls.find(([u]) => u.endsWith('/code-search/query'))[1].body).branch).toBeUndefined()
    await selectOption(user, 'Branch', /dev/)
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(f.mock.calls.filter(([u]) => u.endsWith('/code-search/query'))).toHaveLength(2))
    expect(JSON.parse(f.mock.calls.filter(([u]) => u.endsWith('/code-search/query'))[1][1].body).branch).toBe('dev')
  })
  it('explains when no repository is indexed on the chosen branch (graceful, not an error)', async () => {
    setup(() => ({ body: { results: [], searched_repositories: [], backend: 'Pinecone', branch: 'dev', note: "None of your repositories is indexed on branch 'dev'. Choose another branch, or index it from the Repositories page." } }))
    const user = userEvent.setup()
    renderApp(<CodeSearchPage />, { route: '/app/code-search', withAuth: false })
    await user.type(await screen.findByLabelText('Search query'), 'database')
    await selectOption(user, 'Branch', /dev/)
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText(/None of your repositories is indexed on branch 'dev'/)).toBeInTheDocument()
  })
})
