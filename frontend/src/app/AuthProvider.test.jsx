import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { useAuth } from './AuthProvider'
import { ME, mockFetch, renderApp, unauthorized } from '../test/utils'

afterEach(() => vi.unstubAllGlobals())

function Probe() {
  const { status, logout } = useAuth()
  return <div><p>status:{status}</p><button onClick={logout}>Sign out</button></div>
}
const ui = <Routes><Route path="/login" element={<p>login page</p>} /><Route path="*" element={<Probe />} /></Routes>
const posts = (f) => f.mock.calls.filter(([u, i]) => u.endsWith('/auth/logout') && i.method === 'POST')

describe('AuthProvider logout', () => {
  it('signs out in the UI and goes to /login after the server confirms (regression: 204 but UI stayed signed in)', async () => {
    let loggedOut = false
    const f = mockFetch((u, m) => (u.endsWith('/auth/logout') && m === 'POST' ? (loggedOut = true, { status: 204 }) : u.endsWith('/auth/me') ? (loggedOut ? unauthorized : { body: ME }) : null))
    renderApp(ui, { route: '/app/dashboard' })
    expect(await screen.findByText('status:authenticated')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByText('login page')).toBeInTheDocument()
    expect(posts(f)).toHaveLength(1)
    expect(posts(f)[0][1].headers['X-CSRF-Token']).toBe('csrf123')                 // CSRF header was sent
  })

  it('stays signed in and shows an error when the logout request fails (server session may still be alive)', async () => {
    mockFetch((u, m) => (u.endsWith('/auth/logout') && m === 'POST' ? { status: 500, body: { error: { code: 'internal_error', message: 'x' } } } : u.endsWith('/auth/me') ? { body: ME } : null))
    renderApp(ui, { route: '/app/dashboard' })
    await screen.findByText('status:authenticated')
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByText(/sign out failed/i)).toBeInTheDocument()
    expect(screen.getByText('status:authenticated')).toBeInTheDocument()
    expect(screen.queryByText('login page')).not.toBeInTheDocument()
  })

  it('treats a 401 from logout as already signed out', async () => {
    mockFetch((u, m) => (u.endsWith('/auth/logout') && m === 'POST' ? unauthorized : u.endsWith('/auth/me') ? { body: ME } : null))
    renderApp(ui, { route: '/app/dashboard' })
    await screen.findByText('status:authenticated')
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByText('login page')).toBeInTheDocument()
  })

  it('can sign in again after signing out (the signed-out state does not stick)', async () => {
    let loggedOut = false
    mockFetch((u, m) => (u.endsWith('/auth/logout') && m === 'POST' ? (loggedOut = true, { status: 204 }) : u.endsWith('/auth/me') ? (loggedOut ? unauthorized : { body: ME }) : null))
    const { client } = renderApp(<Routes><Route path="/login" element={<Probe />} /><Route path="*" element={<Probe />} /></Routes>, { route: '/app/x' })
    await screen.findByText('status:authenticated')
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await screen.findByText('status:unauthenticated')
    loggedOut = false                                                              // user completes a new sign-in
    await act(async () => { await client.invalidateQueries({ queryKey: ['me'] }) })
    await waitFor(() => expect(screen.getByText('status:authenticated')).toBeInTheDocument())
  })

  it('a 401 anywhere in the app also ends the session in the UI', async () => {
    mockFetch((u) => (u.endsWith('/auth/me') ? { body: ME } : null))
    renderApp(ui, { route: '/app/dashboard' })
    await screen.findByText('status:authenticated')
    act(() => { window.dispatchEvent(new Event('synaxys:unauthorized')) })
    expect(await screen.findByText('status:unauthenticated')).toBeInTheDocument()
  })
})