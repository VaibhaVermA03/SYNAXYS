import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import { AuthProvider } from '../app/AuthProvider'
import { ThemeProvider } from '../app/ThemeProvider'
import { ToastProvider } from '../components/ui/Toast'

/** handler(url, method, init) -> { status?, body? }. Unmatched requests fail the test loudly. */
export function mockFetch(handler) {
  const fn = vi.fn(async (url, init = {}) => {
    const r = handler(String(url), init.method || 'GET', init)
    if (!r) throw new Error(`Unmocked request: ${init.method || 'GET'} ${url}`)
    const status = r.status ?? 200
    return { ok: status >= 200 && status < 300, status, json: async () => r.body ?? null }
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

/** Opens the custom dropdown named `label` and picks the option named `optionName` (replaces native selectOptions). */
export async function selectOption(user, label, optionName) {
  await user.click(await screen.findByRole('combobox', { name: label }))
  await user.click(await screen.findByRole('option', { name: optionName }))
}

export const ME = { user: { id: 1, login: 'alice', name: 'Alice', avatar_url: null }, csrf_token: 'csrf123',
  integrations: { github_oauth: true, github_app: true, webhook_secret: true, openai: false, pinecone: false, demo_mode: false, demo_login: false } }
export const unauthorized = { status: 401, body: { error: { code: 'unauthorized', message: 'Authentication required' } } }

export function renderApp(ui, { route = '/', withAuth = true } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const tree = (
    <QueryClientProvider client={client}><ThemeProvider><ToastProvider><MemoryRouter initialEntries={[route]}>
      {withAuth ? <AuthProvider>{ui}</AuthProvider> : ui}
    </MemoryRouter></ToastProvider></ThemeProvider></QueryClientProvider>
  )
  return { client, ...render(tree) }
}
