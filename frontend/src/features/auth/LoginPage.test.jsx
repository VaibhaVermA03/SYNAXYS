import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import LoginPage from './LoginPage'
import { ME, mockFetch, renderApp, unauthorized } from '../../test/utils'

afterEach(() => vi.unstubAllGlobals())
const cfg = (o = {}) => ({ github_oauth: true, github_app: true, webhook_secret: true, openai: false, pinecone: false, demo_mode: false, demo_login: false, ...o })
const handler = (config) => (url) => (url.endsWith('/auth/me') ? unauthorized : url.endsWith('/auth/config') ? { body: config } : null)
const ui = <Routes><Route path="/login" element={<LoginPage />} /></Routes>

describe('LoginPage', () => {
  it('links to the server-side OAuth flow when configured', async () => {
    mockFetch(handler(cfg()))
    renderApp(ui, { route: '/login' })
    expect(await screen.findByRole('link', { name: /continue with github/i })).toHaveAttribute('href', '/api/v1/auth/github/login')
  })

  it('shows a clear configuration message instead of a dead button', async () => {
    mockFetch(handler(cfg({ github_oauth: false })))
    renderApp(ui, { route: '/login' })
    expect(await screen.findByRole('alert')).toHaveTextContent(/GITHUB_CLIENT_ID/)
    expect(screen.queryByRole('link', { name: /continue with github/i })).not.toBeInTheDocument()
  })

  it('explains callback errors', async () => {
    mockFetch(handler(cfg()))
    renderApp(ui, { route: '/login?error=invalid_state' })
    expect(await screen.findByText(/could not be verified/i)).toBeInTheDocument()
  })

  it('never offers a sample-data sign-in, even if the server reports it as enabled; GitHub is the only way in', async () => {
    mockFetch(handler(cfg({ demo_login: true })))
    renderApp(ui, { route: '/login' })
    expect(await screen.findByRole('link', { name: /continue with github/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sample data|explore|demo/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/sample data|demo mode/i)).not.toBeInTheDocument()
    expect(screen.getAllByRole('button')).toHaveLength(1)                                   // only the theme toggle
  })

  it('redirects authenticated users away from login', async () => {
    mockFetch((url) => (url.endsWith('/auth/me') ? { body: ME } : { body: cfg() }))
    renderApp(<Routes><Route path="/login" element={<LoginPage />} /><Route path="/app/dashboard" element={<p>dash</p>} /></Routes>, { route: '/login' })
    expect(await screen.findByText('dash')).toBeInTheDocument()
  })
})

describe('LoginPage — split layout', () => {
  it('shows the showcase only from the lg breakpoint, plain background effect on mobile, and a theme toggle', async () => {
    mockFetch(handler(cfg()))
    const { container } = renderApp(ui, { route: '/login' })
    await screen.findByRole('link', { name: /continue with github/i })
    const showcase = container.querySelector('section[aria-hidden="true"]')
    expect(showcase).toHaveClass('hidden', 'lg:flex')                                   // right half: desktop only, decorative
    expect(showcase).toHaveTextContent(/smarter reviews/i)
    expect(container.querySelector('.lg\\:hidden[aria-hidden="true"]')).toBeInTheDocument()   // mobile: ambient background only
    expect(container.firstChild).toHaveClass('lg:grid-cols-2')
    expect(container.firstChild).toHaveClass('h-dvh', 'overflow-hidden')                // one fixed screen, no page scroll
    expect(screen.getByRole('button', { name: /switch to (dark|light) mode/i })).toBeInTheDocument()
  })

  it('has no feature tags in the showcase, centres both columns vertically and shows a bigger bold wordmark', async () => {
    mockFetch(handler(cfg()))
    const { container } = renderApp(ui, { route: '/login' })
    await screen.findByRole('link', { name: /continue with github/i })
    expect(screen.queryByText(/evidence-backed findings|human-approved comments|semantic code search|repository-scoped access/i)).not.toBeInTheDocument()
    expect(container.querySelector('section[aria-hidden="true"] ul')).toBeNull()
    expect(container.querySelector('section[aria-hidden="true"] .m-auto')).toBeInTheDocument()   // showcase content centred (auto margins never clip)
    expect(container.querySelector('main .m-auto')).toBeInTheDocument()                            // login content centred
    expect(container.querySelector('main')).toHaveClass('overflow-y-auto')                          // safety net only when the viewport is truly tiny
    expect(screen.getByText('SYNAXYS')).toHaveClass('text-3xl', '[-webkit-text-stroke:0.035em_currentColor]', 'font-pixel')
  })

  it('keeps exactly one alert on the page when sign-in is not configured (showcase adds none)', async () => {
    mockFetch(handler(cfg({ github_oauth: false })))
    renderApp(ui, { route: '/login' })
    expect(await screen.findAllByRole('alert')).toHaveLength(1)
  })
})
