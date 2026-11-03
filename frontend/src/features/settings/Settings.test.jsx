import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SettingsPage from './SettingsPage'
import IntegrationsPage from './IntegrationsPage'
import { ME, mockFetch, renderApp } from '../../test/utils'

afterEach(() => vi.unstubAllGlobals())
const item = (o) => ({ key: 'openai', label: 'OpenAI', configured: true, detail: 'ok', env: ['OPENAI_API_KEY'], ...o })
const integ = (o = {}) => ({ items: [item({}), item({ key: 'pinecone', label: 'Pinecone', configured: false, detail: 'Not configured: indexing and code search are unavailable.', env: ['PINECONE_API_KEY', 'PINECONE_INDEX_NAME'] })],
  environment: 'development', webhook_url: 'http://localhost:8000/api/v1/webhooks/github', oauth_callback_url: 'http://localhost:8000/api/v1/auth/github/callback', install_url: 'https://github.com/apps/x/installations/new',
  demo_login: false, mock_llm: false, vector_backend: 'pinecone', github_token_stored: true, ...o })
const repo = (o = {}) => ({ id: 5, full_name: 'alice/app', role: 'owner', is_demo: false, is_enabled: true, ...o })
const policy = (o = {}) => ({ require_approval: true, auto_publish: false, allowed_actions: ['opened', 'synchronize', 'reopened'], max_files: 50, max_patch_bytes: 200000, index_enabled: true, ...o })
const route = (extra = () => null, i = integ()) => (u, m) => extra(u, m) || (u.endsWith('/auth/me') ? { body: ME } : u.endsWith('/settings/integrations') ? { body: i } : u.includes('/settings/audit') ? { body: [] }
  : u.startsWith('/api/v1/github/repositories/5/config') && m === 'GET' ? { body: policy() } : u.startsWith('/api/v1/github/repositories') ? { body: { items: [repo(), repo({ id: 6, full_name: 'org/member', role: 'member' })], total: 2, page: 1, page_size: 100 } } : null)
const calls = (f, method, suffix) => f.mock.calls.filter(([u, i]) => i.method === method && u.endsWith(suffix))

describe('SettingsPage', () => {
  it('shows account, lets the user revoke stored credentials only after confirming', async () => {
    const f = mockFetch(route((u, m) => (m === 'DELETE' && u.endsWith('/github/credentials') ? { status: 204 } : null)))
    renderApp(<SettingsPage />)
    expect(await screen.findByText('@alice · signed in with GitHub')).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: /revoke stored github credentials/i }))
    expect(screen.getByRole('dialog')).toHaveTextContent(/does not uninstall the github app/i)
    expect(calls(f, 'DELETE', '/github/credentials')).toHaveLength(0)
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(calls(f, 'DELETE', '/github/credentials')).toHaveLength(1))
  })

  it('does not offer revoke when no token is stored, and renders readable activity', async () => {
    const noToken = route(() => null, integ({ github_token_stored: false }))
    const audit = [{ id: 1, action: 'review.publish', target_type: 'review', target_id: '4', created_at: '2026-01-01T00:00:00Z' }]
    mockFetch((u, m) => (u.includes('/settings/audit') ? { body: audit } : noToken(u, m)))
    renderApp(<SettingsPage />)
    expect(await screen.findByText('No token stored')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument()
    expect(await screen.findByText('Published comments to GitHub')).toBeInTheDocument()
  })
})

describe('IntegrationsPage', () => {
  it('shows configured vs missing integrations with the env vars to set, and never secret values', async () => {
    mockFetch(route()); renderApp(<IntegrationsPage />)
    expect(await screen.findByText('Not configured', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByText('PINECONE_API_KEY')).toBeInTheDocument()
    expect(screen.getByText(/never shown here/i)).toBeInTheDocument()
    expect(screen.getByText('http://localhost:8000/api/v1/webhooks/github')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /install the github app/i })).toBeInTheDocument()
  })

  it('labels local demo features so they are not mistaken for real integrations', async () => {
    mockFetch(route(() => null, integ({ demo_login: true, mock_llm: true, vector_backend: 'memory' }))); renderApp(<IntegrationsPage />)
    expect(await screen.findByText(/mock reviewer \(not AI\)/i)).toBeInTheDocument()
    expect(screen.getByText(/in-memory search store/i)).toBeInTheDocument()
  })

  it('lists only repositories the user administers in the policy form and saves manual approval', async () => {
    const f = mockFetch(route((u, m) => (m === 'PATCH' && u.endsWith('/5/config') ? { body: policy() } : null))); renderApp(<IntegrationsPage />)
    await userEvent.click(await screen.findByRole('combobox', { name: 'Repository' }))
    expect(screen.getByRole('option', { name: 'alice/app' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'org/member' })).not.toBeInTheDocument()   // non-admin repositories are not offered
    await userEvent.keyboard('{Escape}')
    await screen.findByLabelText(/manual approval/i)
    await userEvent.click(screen.getByRole('button', { name: /save policy/i }))
    await waitFor(() => expect(calls(f, 'PATCH', '/5/config')).toHaveLength(1))
    expect(JSON.parse(calls(f, 'PATCH', '/5/config')[0][1].body)).toMatchObject({ require_approval: true, allowed_actions: ['opened', 'synchronize', 'reopened'], max_files: 50 })
  })

  it('requires an explicit confirmation before enabling auto-publish and explains the risk', async () => {
    const f = mockFetch(route((u, m) => (m === 'PATCH' ? { body: policy({ auto_publish: true, require_approval: false }) } : null))); renderApp(<IntegrationsPage />)
    await userEvent.click(await screen.findByLabelText(/auto-publish/i))
    await userEvent.click(screen.getByRole('button', { name: /save policy/i }))
    expect(screen.getByRole('dialog')).toHaveTextContent(/without anyone approving them/i)
    expect(calls(f, 'PATCH', '/5/config')).toHaveLength(0)                                   // nothing saved before confirming
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /enable auto-publish/i }))
    await waitFor(() => expect(calls(f, 'PATCH', '/5/config')).toHaveLength(1))
    expect(JSON.parse(calls(f, 'PATCH', '/5/config')[0][1].body)).toMatchObject({ auto_publish: true })
  })

  it('refuses to save with no events selected and shows server errors', async () => {
    mockFetch(route((u, m) => (m === 'PATCH' ? { status: 400, body: { error: { code: 'conflicting_policy', message: 'auto_publish and require_approval cannot both be enabled.' } } } : null))); renderApp(<IntegrationsPage />)
    await screen.findByLabelText(/manual approval/i)
    for (const name of [/pull request opened/i, /new commits pushed/i, /pull request reopened/i]) await userEvent.click(screen.getByLabelText(name))
    expect(screen.getByRole('button', { name: /save policy/i })).toBeDisabled()
    await userEvent.click(screen.getByLabelText(/pull request opened/i))
    await userEvent.click(screen.getByRole('button', { name: /save policy/i }))
    expect(await screen.findByText(/cannot both be enabled/i)).toBeInTheDocument()
  })
})
