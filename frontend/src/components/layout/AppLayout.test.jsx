import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import AppLayout from './AppLayout'
import { ME, mockFetch, renderApp } from '../../test/utils'

const ui = (
  <Routes>
    <Route path="/login" element={<p>login page</p>} />
    <Route path="/app" element={<AppLayout />}>
      <Route path="dashboard" element={<p>dash page</p>} />
      <Route path="reviews" element={<p>reviews page</p>} />
      <Route path="settings" element={<p>settings page</p>} />
    </Route>
  </Routes>
)
const setup = (route = '/app/dashboard', extra = () => null) => { const f = mockFetch((u, m) => extra(u, m) || (u.endsWith('/auth/me') ? { body: ME } : null)); return { f, ...renderApp(ui, { route }) } }
const asDesktop = () => Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: (q) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }) })
const sidebar = () => document.getElementById('app-sidebar')

beforeEach(() => { localStorage.clear() })
afterEach(() => { vi.unstubAllGlobals(); delete window.matchMedia; localStorage.clear(); document.documentElement.classList.remove('dark'); document.body.style.overflow = '' })

describe('AppLayout — sidebar', () => {
  it('mobile: drawer is closed by default, opens from the header button, locks scrolling, closes on Escape and on navigation', async () => {
    setup()
    await screen.findByText('alice')
    expect(sidebar()).toHaveAttribute('aria-hidden', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Open sidebar' }))
    expect(sidebar()).toHaveAttribute('aria-hidden', 'false')
    expect(screen.getByRole('button', { name: 'Close sidebar' })).toHaveAttribute('aria-expanded', 'true')
    expect(document.body.style.overflow).toBe('hidden')
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(sidebar()).toHaveAttribute('aria-hidden', 'true'))
    expect(document.body.style.overflow).toBe('')
    await userEvent.click(screen.getByRole('button', { name: 'Open sidebar' }))
    await userEvent.click(screen.getByRole('link', { name: 'Code Reviews' }))
    expect(await screen.findByText('reviews page')).toBeInTheDocument()
    expect(sidebar()).toHaveAttribute('aria-hidden', 'true')
  })

  it('mobile: focus moves into the drawer when it opens and returns to the header button when it closes', async () => {
    setup(); await screen.findByText('alice')
    await userEvent.click(screen.getByRole('button', { name: 'Open sidebar' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Close navigation' })).toHaveFocus())
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open sidebar' })).toHaveFocus())
  })

  it('desktop: open by default; toggling closes it, shifts the content back to the centre and remembers the choice', async () => {
    asDesktop(); setup()
    await screen.findByText('alice')
    const wrapper = screen.getByRole('main').parentElement
    expect(sidebar()).toHaveAttribute('aria-hidden', 'false')
    expect(wrapper).toHaveClass('lg:pl-60')
    await userEvent.click(screen.getByRole('button', { name: 'Close sidebar' }))
    expect(sidebar()).toHaveAttribute('aria-hidden', 'true')
    expect(sidebar()).toHaveClass('-translate-x-full')
    expect(wrapper).toHaveClass('lg:pl-0')
    expect(localStorage.getItem('synaxys-sidebar')).toBe('closed')
    await userEvent.click(screen.getByRole('button', { name: 'Open sidebar' }))
    expect(wrapper).toHaveClass('lg:pl-60')
    expect(sidebar()).toHaveClass('translate-x-0')
  })

  it('desktop: a remembered "closed" preference is restored on load', async () => {
    asDesktop(); localStorage.setItem('synaxys-sidebar', 'closed'); setup()
    await screen.findByText('alice')
    expect(sidebar()).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('main').parentElement).toHaveClass('lg:pl-0')
  })

  it('animates: sidebar and content share the same transition classes', async () => {
    setup(); await screen.findByText('alice')
    expect(sidebar()).toHaveClass('transition-transform', 'duration-300')
    expect(screen.getByRole('main').parentElement).toHaveClass('transition-[padding-left]', 'duration-300')
  })

  it('lists all navigation links with icons and marks the current page', async () => {
    asDesktop(); setup()
    await screen.findByText('alice')
    const links = screen.getAllByRole('link').filter((a) => a.closest('nav'))
    expect(links.map((a) => a.textContent)).toEqual(['Dashboard', 'Repositories', 'Pull Requests', 'Code Reviews', 'Codebase Search', 'Review Rules', 'Settings'])
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page')
    expect(links.every((a) => a.querySelector('svg'))).toBe(true)
  })
})

describe('AppLayout — header', () => {
  it('shows the page name in one line with an ellipsis when it does not fit', async () => {
    setup(); await screen.findByText('alice')
    const h1 = screen.getByRole('heading', { level: 1 })
    expect(h1).toHaveTextContent('Dashboard')
    expect(h1).toHaveClass('truncate', 'whitespace-nowrap', 'min-w-0', 'flex-1')
  })

  it('theme button: tooltip text follows the theme and clicking switches it', async () => {
    setup(); await screen.findByText('alice')
    expect(screen.getByRole('button', { name: 'Switch to dark mode' })).toBeInTheDocument()
    expect(screen.getByText('Switch to dark mode')).toHaveClass('md:block', 'hidden')        // tooltip: desktop only, below the button
    await userEvent.click(screen.getByRole('button', { name: 'Switch to dark mode' }))
    expect(document.documentElement).toHaveClass('dark')
    expect(screen.getByRole('button', { name: 'Switch to light mode' })).toBeInTheDocument()
    expect(screen.getByText('Switch to light mode')).toBeInTheDocument()
  })

  it('profile button opens a popup with a Settings link that navigates; Escape and outside click close it', async () => {
    setup(); await screen.findByText('alice')
    const btn = screen.getByRole('button', { name: 'Open profile menu' })
    await userEvent.click(btn)
    const menu = screen.getByRole('menu', { name: 'Profile' })
    expect(menu).toHaveTextContent('@alice')
    expect(screen.getByRole('menuitem', { name: 'Settings' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
    expect(btn).toHaveFocus()
    await userEvent.click(btn)
    await userEvent.click(document.body)
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
    await userEvent.click(btn)
    await userEvent.click(screen.getByRole('menuitem', { name: 'Settings' }))
    expect(await screen.findByText('settings page')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Settings')
  })

  it('sign out keeps its accessible name; the text label is hidden below the md breakpoint (icon only on mobile)', async () => {
    const { f } = setup('/app/dashboard', (u, m) => (u.endsWith('/auth/logout') && m === 'POST' ? { status: 204 } : null))
    await screen.findByText('alice')
    const btn = screen.getByRole('button', { name: 'Sign out' })
    const label = btn.querySelector('span')
    expect(label).toHaveTextContent('Sign out')
    expect(label).toHaveClass('hidden', 'md:inline')
    expect(btn.querySelector('svg')).toBeInTheDocument()
    await userEvent.click(btn)
    expect(await screen.findByText('login page')).toBeInTheDocument()
    expect(f.mock.calls.some(([u, i]) => u.endsWith('/auth/logout') && i.method === 'POST')).toBe(true)
  })
})

describe('Logo', () => {
  it('shows the SVG logo (inverted in dark mode) next to the SYNAXYS wordmark in the pixel font', async () => {
    setup(); await screen.findByText('alice')
    const img = document.querySelector('img[src="/brand/synaxys-logo.svg"]')
    expect(img).toHaveClass('dark:invert')
    expect(screen.getByText('SYNAXYS')).toHaveClass('font-pixel', 'text-xl', '[-webkit-text-stroke:0.035em_currentColor]')   // sidebar wordmark: larger and bolder
  })

  it('falls back to the wordmark alone when the logo file is missing', async () => {
    setup(); await screen.findByText('alice')
    fireEvent.error(document.querySelector('img[src="/brand/synaxys-logo.svg"]'))
    expect(document.querySelector('img[src="/brand/synaxys-logo.svg"]')).toBeNull()
    expect(screen.getByText('SYNAXYS')).toBeInTheDocument()
  })
})
