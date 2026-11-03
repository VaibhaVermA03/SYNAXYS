import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import ProtectedRoute from './ProtectedRoute'
import { ME, mockFetch, renderApp, unauthorized } from '../test/utils'

afterEach(() => vi.unstubAllGlobals())
const ui = (
  <Routes>
    <Route path="/login" element={<p>login page</p>} />
    <Route element={<ProtectedRoute />}><Route path="/app/dashboard" element={<p>secret</p>} /></Route>
  </Routes>
)

describe('ProtectedRoute', () => {
  it('redirects unauthenticated visitors to login', async () => {
    mockFetch(() => unauthorized)
    renderApp(ui, { route: '/app/dashboard' })
    expect(await screen.findByText('login page')).toBeInTheDocument()
    expect(screen.queryByText('secret')).not.toBeInTheDocument()
  })

  it('renders content for authenticated users', async () => {
    mockFetch(() => ({ body: ME }))
    renderApp(ui, { route: '/app/dashboard' })
    expect(await screen.findByText('secret')).toBeInTheDocument()
  })

  it('shows a retryable error when the server is down (not a login redirect)', async () => {
    mockFetch(() => ({ status: 500, body: { error: { code: 'internal_error', message: 'x' } } }))
    renderApp(ui, { route: '/app/dashboard' })
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})
