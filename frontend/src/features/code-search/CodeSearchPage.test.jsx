import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CodeSearchPage from './CodeSearchPage'
import { mockFetch, renderApp, selectOption } from '../../test/utils'

afterEach(() => vi.unstubAllGlobals())
const repo = (o = {}) => ({ id: 1, full_name: 'alice/app', is_enabled: true, index_status: 'indexed', role: 'owner', ...o })
const hit = { id: 'a#0001', score: 0.71, repository: 'alice/app', repository_id: 1, path: 'app/db.py', start_line: 3, end_line: 9, language: 'python', branch: 'main', commit: 'abc',
  snippet: 'def open_connection(pool):\n    return pool.acquire()', explanation: 'strong semantic similarity (0.71); code mentions pool', github_url: 'https://github.com/alice/app/blob/abc/app/db.py#L3-L9' }
const out = (o = {}) => ({ results: [hit], searched_repositories: ['alice/app'], backend: 'Pinecone', note: null, ...o })
const setup = (search = () => ({ body: out() }), repos = [repo()]) => mockFetch((u, m) => (u.startsWith('/api/v1/github/repositories') ? { body: { items: repos, total: repos.length, page: 1, page_size: 100 } }
  : u.endsWith('/code-search/query') && m === 'POST' ? search(u, m) : null))
const search = async (text = 'connection pool') => { await userEvent.type(await screen.findByLabelText('Search query'), text); await userEvent.click(screen.getByRole('button', { name: 'Search' })) }

describe('CodeSearchPage', () => {
  it('shows snippet, path and lines, repository, relevance explanation and a GitHub link', async () => {
    setup(); renderApp(<CodeSearchPage />, { withAuth: false })
    await search()
    expect(await screen.findByText('app/db.py:3–9')).toBeInTheDocument()
    expect(screen.getByText(/return pool.acquire/)).toBeInTheDocument()
    expect(screen.getByText(/strong semantic similarity/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open on github/i })).toHaveAttribute('href', expect.stringContaining('/blob/abc/app/db.py#L3-L9'))
    expect(screen.getByText(/1 result\(s\) from alice\/app/)).toBeInTheDocument()
  })

  it('sends the selected repository and language and trims the query', async () => {
    const f = setup(); renderApp(<CodeSearchPage />, { withAuth: false })
    await selectOption(userEvent, 'Repository', 'alice/app')
    await selectOption(userEvent, 'Language', 'python')
    await search('  pool  ')
    await waitFor(() => expect(f.mock.calls.some(([u]) => u.endsWith('/code-search/query'))).toBe(true))
    expect(JSON.parse(f.mock.calls.find(([u]) => u.endsWith('/code-search/query'))[1].body)).toEqual({ query: 'pool', repository_id: 1, language: 'python', top_k: 10 })
  })

  it('only offers repositories that are connected and indexed, and explains when there are none', async () => {
    setup(undefined, [repo({ id: 2, full_name: 'alice/raw', index_status: 'not_indexed' })]); renderApp(<CodeSearchPage />, { withAuth: false })
    expect(await screen.findByText(/no indexed repositories yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /go to repositories/i })).toBeInTheDocument()
    expect(screen.queryByLabelText('Search query')).not.toBeInTheDocument()
  })

  it('shows loading, empty, demo-embedding note and configuration errors without fake results', async () => {
    setup(() => ({ body: out({ results: [], note: 'Local demo embeddings (lexical matching, not semantic).' }) })); renderApp(<CodeSearchPage />, { withAuth: false })
    await search('nothing here')
    expect(await screen.findByText(/no matches/i)).toBeInTheDocument()
    expect(screen.getByText(/not semantic/i)).toBeInTheDocument()
    vi.unstubAllGlobals()
    setup(() => ({ status: 503, body: { error: { code: 'pinecone_not_configured', message: 'Pinecone is not configured. Set PINECONE_API_KEY and PINECONE_INDEX_NAME.' } } }))
    renderApp(<CodeSearchPage />, { withAuth: false })
    await search('pool')
    expect(await screen.findByText(/PINECONE_API_KEY/)).toBeInTheDocument()
    expect(screen.queryByText('app/db.py:3–9')).not.toBeInTheDocument()
  })

  it('does not search for queries shorter than two characters', async () => {
    const f = setup(); renderApp(<CodeSearchPage />, { withAuth: false })
    await userEvent.type(await screen.findByLabelText('Search query'), 'a')
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled()
    expect(f.mock.calls.some(([u]) => u.endsWith('/code-search/query'))).toBe(false)
  })
})
