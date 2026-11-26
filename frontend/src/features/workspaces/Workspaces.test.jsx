import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import WorkspacesPage from './WorkspacesPage'
import InvitationPage from './InvitationPage'
import NotificationsPage from '../notifications/NotificationsPage'
import AccountPage from '../settings/AccountPage'
import { WorkspaceProvider } from '../../app/WorkspaceProvider'
import { mockFetch, renderApp } from '../../test/utils'

// Phase 4 (batch 16): workspaces, invitations, notifications, account. NOT RUN in the authoring sandbox.
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })
const WS = { id: 1, name: "alice's workspace", role: 'owner', invite_policy: 'admin', members: 2, repositories: 1 }
const MEMBERS = [{ user_id: 1, login: 'alice', role: 'owner', joined_at: '2026-01-01T00:00:00Z' }, { user_id: 2, login: 'bob', role: 'member', joined_at: '2026-01-02T00:00:00Z' }]
const ME = { user: { id: 1, login: 'alice', name: 'Alice', avatar_url: null }, csrf_token: 'csrf', integrations: {}, is_admin: false }
const meRoute = (u) => (u.endsWith('/auth/me') ? { body: ME } : null)
const calls = (f, method, suffix) => f.mock.calls.filter(([u, i]) => (i.method || 'GET') === method && u.includes(suffix))
const wsPage = (extra = () => null, ws = WS) => mockFetch((u, m) => extra(u, m) || meRoute(u)
  || (u.endsWith('/auth/me') ? { body: ME } : u.endsWith('/workspaces') ? { body: [ws] } : u.includes('/members') ? { body: MEMBERS } : u.includes('/invitations/mine') ? { body: [] } : u.includes('/invitations') ? { body: [] }
    : u.includes('/audit') ? { body: [{ id: 1, action: 'workspace.create', actor: 'alice', created_at: '2026-01-01T00:00:00Z' }] } : null))
const mount = (ui) => renderApp(<WorkspaceProvider>{ui}</WorkspaceProvider>, { withAuth: true, route: '/app/settings/workspaces' })

describe('workspace management', () => {
  it('shows members with role controls only to the owner and sends the active workspace header', async () => {
    const f = wsPage()
    mount(<WorkspacesPage />)
    expect(await screen.findByText('bob')).toBeInTheDocument()
    expect(screen.getByLabelText('Role of bob')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /make owner/i })).toBeInTheDocument()
    await waitFor(() => expect(f.mock.calls.some(([u, i]) => u.includes('/members') && i.headers?.['X-Workspace-Id'] === '1')).toBe(true))
  })

  it('hides management controls from plain members', async () => {
    wsPage(() => null, { ...WS, role: 'member' })
    mount(<WorkspacesPage />)
    await screen.findByText('bob')
    expect(screen.queryByLabelText('Role of bob')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove bob/i })).not.toBeInTheDocument()
    expect(screen.queryByText('Workspace activity')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /leave workspace/i })).toBeInTheDocument()
  })

  it('creates an invitation and shows the one-time link', async () => {
    const f = wsPage((u, m) => (m === 'POST' && u.endsWith('/workspaces/1/invitations') ? { status: 201, body: { id: 5, login: 'carol', role: 'member', status: 'pending', expires_at: '2026-01-08T00:00:00Z', created_at: '2026-01-01T00:00:00Z', token: 'T'.repeat(43) } } : null))
    mount(<WorkspacesPage />)
    await userEvent.type(await screen.findByLabelText('GitHub username'), 'carol')
    await userEvent.click(screen.getByRole('button', { name: /^invite$/i }))
    expect(await screen.findByText(new RegExp(`/app/invitations/${'T'.repeat(43)}`))).toBeInTheDocument()
    expect(JSON.parse(calls(f, 'POST', '/invitations')[0][1].body)).toEqual({ login: 'carol', role: 'member' })
  })

  it('requires the exact workspace name before deleting', async () => {
    const f = wsPage((u, m) => (m === 'POST' && u.endsWith('/delete') ? { status: 204, body: null } : null))
    mount(<WorkspacesPage />)
    await userEvent.click(await screen.findByRole('button', { name: /delete workspace/i }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /delete workspace/i }))
    expect(calls(f, 'POST', '/delete')).toHaveLength(0)                                    // nothing without the typed name
    await userEvent.type(within(dialog).getByLabelText(/type the workspace name/i), WS.name)
    await userEvent.click(within(dialog).getByRole('button', { name: /delete workspace/i }))
    await waitFor(() => expect(JSON.parse(calls(f, 'POST', '/delete')[0][1].body)).toEqual({ confirm_name: WS.name }))
  })
})

describe('invitation page', () => {
  it('accepts with the token from the link and reports a wrong-user/expired answer', async () => {
    const f = mockFetch((u) => (u.endsWith('/workspaces/invitations/accept') ? { status: 404, body: { error: { code: 'not_found', message: 'Invitation not found' } } } : u.endsWith('/workspaces') ? { body: [] } : null))
    renderApp(<WorkspaceProvider><Routes><Route path="/app/invitations/:token" element={<InvitationPage />} /></Routes></WorkspaceProvider>, { route: '/app/invitations/abc123', withAuth: false })
    await userEvent.click(await screen.findByRole('button', { name: /accept invitation/i }))
    expect(await screen.findByText(/invitation not found/i)).toBeInTheDocument()
    expect(JSON.parse(calls(f, 'POST', '/accept')[0][1].body)).toEqual({ token: 'abc123' })
  })
})

describe('notification centre', () => {
  const N = (o) => ({ id: 1, kind: 'review_completed', title: 'Review completed: alice/app #4', body: null, link: '/app/reviews/3', workspace_id: 1, read: false, created_at: '2026-01-01T00:00:00Z', ...o })
  it('lists notifications, marks one read and marks all read', async () => {
    const f = mockFetch((u, m) => (m === 'POST' ? { status: 204, body: m === 'POST' && u.endsWith('/read-all') ? { marked: 2 } : null }
      : u.startsWith('/api/v1/notifications') ? { body: { items: [N(), N({ id: 2, kind: 'review_failed', title: 'Review failed', read: true })], total: 2, unread: 1, page: 1, page_size: 20 } } : null))
    renderApp(<NotificationsPage />, { withAuth: false })
    expect(await screen.findByText('Review completed: alice/app #4')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^mark as read$/i }))
    await waitFor(() => expect(calls(f, 'POST', '/notifications/1/read')).toHaveLength(1))
    await userEvent.click(screen.getByRole('button', { name: /mark all as read/i }))
    await waitFor(() => expect(calls(f, 'POST', '/read-all')).toHaveLength(1))
  })
  it('shows an empty state', async () => {
    mockFetch(() => ({ body: { items: [], total: 0, unread: 0, page: 1, page_size: 20 } }))
    renderApp(<NotificationsPage />, { withAuth: false })
    expect(await screen.findByText(/no notifications yet/i)).toBeInTheDocument()
  })
})

describe('account settings', () => {
  it('requests an export and offers the download link only when ready', async () => {
    const ex = (o) => ({ id: 1, status: 'ready', size_bytes: 2048, created_at: '2026-01-01T00:00:00Z', expires_at: '2026-01-02T00:00:00Z', downloaded_at: null, error: null, ...o })
    const f = mockFetch((u, m) => (u.endsWith('/auth/me') ? { body: ME } : m === 'POST' && u.endsWith('/account/exports') ? { status: 202, body: ex({ status: 'pending' }) } : u.endsWith('/account/exports') ? { body: [ex(), ex({ id: 2, status: 'pending', size_bytes: 0 })] } : null))
    renderApp(<AccountPage />, { withAuth: true })
    expect(await screen.findByRole('link', { name: /download/i })).toHaveAttribute('href', expect.stringContaining('/account/exports/1/download'))
    expect(screen.getAllByRole('link', { name: /download/i })).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: /request export/i }))
    await waitFor(() => expect(calls(f, 'POST', '/account/exports')).toHaveLength(1))
  })
  it('needs the typed username to delete and tells the user to sign in again after a 403', async () => {
    const f = mockFetch((u, m) => (u.endsWith('/auth/me') ? { body: ME } : m === 'POST' && u.endsWith('/account/delete') ? { status: 403, body: { error: { code: 'forbidden', message: 'sign in again' } } } : u.endsWith('/account/exports') ? { body: [] } : null))
    renderApp(<AccountPage />, { withAuth: true })
    await userEvent.click(await screen.findByRole('button', { name: /delete my account/i }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /delete account/i }))
    expect(calls(f, 'POST', '/account/delete')).toHaveLength(0)                              // wrong/empty confirmation: nothing is sent
    await userEvent.type(within(dialog).getByLabelText(/type your github username/i), 'alice')
    await userEvent.click(within(dialog).getByRole('button', { name: /delete account/i }))
    expect(await screen.findByText(/sign in with github again/i)).toBeInTheDocument()
    expect(JSON.parse(calls(f, 'POST', '/account/delete')[0][1].body)).toEqual({ confirm_login: 'alice' })
  })
})
