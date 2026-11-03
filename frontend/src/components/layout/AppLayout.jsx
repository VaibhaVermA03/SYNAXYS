import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { ClipboardCheck, Folder, GitPullRequest, LayoutGrid, LogOut, PanelLeft, Search, Settings, SlidersHorizontal, X } from 'lucide-react'
import Logo from './Logo'
import ProfileMenu from './ProfileMenu'
import ThemeToggle from './ThemeToggle'
import { useAuth } from '../../app/AuthProvider'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { Button } from '../ui'
import { cn } from '../../lib/utils'

export const NAV = [
  { to: '/app/dashboard', label: 'Dashboard', icon: LayoutGrid },
  { to: '/app/repositories', label: 'Repositories', icon: Folder },
  { to: '/app/pull-requests', label: 'Pull Requests', icon: GitPullRequest },
  { to: '/app/reviews', label: 'Code Reviews', icon: ClipboardCheck },
  { to: '/app/code-search', label: 'Codebase Search', icon: Search },
  { to: '/app/rules', label: 'Review Rules', icon: SlidersHorizontal },
  { to: '/app/settings', label: 'Settings', icon: Settings },
]

const STORAGE_KEY = 'synaxys-sidebar'
const EASE = 'duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]' // shared by the sidebar slide and the content shift so they move together
const titleFor = (path) => NAV.find((n) => path.startsWith(n.to))?.label || 'SYNAXYS'

function readPref() {
  try { return localStorage.getItem(STORAGE_KEY) !== 'closed' } catch { return true }
}

function Sidebar({ open, onClose, closeRef }) {
  return (
    <aside
      id="app-sidebar" aria-label="Sidebar" aria-hidden={!open} inert={open ? undefined : ''}
      className={cn('fixed inset-y-0 left-0 z-40 flex w-64 max-w-[85vw] flex-col border-r border-border bg-surface transition-transform lg:w-60', EASE,
        open ? 'translate-x-0 shadow-xl lg:shadow-none' : '-translate-x-full')}
    >
      <div className="flex h-14 shrink-0 items-center justify-between px-4">
        <Logo />
        <Button ref={closeRef} variant="ghost" className="px-2 lg:hidden" aria-label="Close navigation" onClick={onClose}><X className="h-[18px] w-[18px]" strokeWidth={1.5} aria-hidden /></Button>
      </div>
      <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-3">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to} to={to} onClick={onClose}
            className={({ isActive }) => cn('flex items-center gap-3 rounded-xl px-3 py-2.5 font-pixel text-[13px] tracking-wide transition-colors',
              isActive ? 'bg-accent/10 text-accent-ink' : 'text-muted hover:bg-surface-2 hover:text-fg')}
          >
            <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.5} aria-hidden />{label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

export default function AppLayout() {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()
  const isDesktop = useMediaQuery('(min-width: 1024px)')
  const [desktopOpen, setDesktopOpen] = useState(readPref) // remembered between visits
  const [mobileOpen, setMobileOpen] = useState(false)
  const open = isDesktop ? desktopOpen : mobileOpen
  const title = titleFor(pathname)
  const toggleRef = useRef(null)
  const closeRef = useRef(null)
  const drawerWasOpen = useRef(false)

  useEffect(() => { setMobileOpen(false) }, [pathname, isDesktop])
  useEffect(() => { try { localStorage.setItem(STORAGE_KEY, desktopOpen ? 'open' : 'closed') } catch { /* storage unavailable */ } }, [desktopOpen])

  // Mobile drawer: Esc closes it and the page behind does not scroll.
  useEffect(() => {
    if (isDesktop || !mobileOpen) return undefined
    const onKey = (e) => { if (e.key === 'Escape') setMobileOpen(false) }
    const prev = document.body.style.overflow
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [isDesktop, mobileOpen])

  // Mobile drawer focus: move focus into the drawer when it opens, back to the header button when it closes.
  useEffect(() => {
    if (isDesktop) return
    if (mobileOpen) { closeRef.current?.focus(); drawerWasOpen.current = true }
    else if (drawerWasOpen.current) { toggleRef.current?.focus(); drawerWasOpen.current = false }
  }, [mobileOpen, isDesktop])

  const toggle = () => (isDesktop ? setDesktopOpen((o) => !o) : setMobileOpen((o) => !o))

  return (
    <div className="min-h-screen">
      <Sidebar open={open} onClose={() => setMobileOpen(false)} closeRef={closeRef} />
      <div className={cn('fixed inset-0 z-30 bg-black/50 transition-opacity lg:hidden', EASE, mobileOpen ? 'opacity-100' : 'pointer-events-none opacity-0')} onClick={() => setMobileOpen(false)} aria-hidden />

      <div className={cn('min-h-screen transition-[padding-left]', EASE, desktopOpen ? 'lg:pl-60' : 'lg:pl-0')}>
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-border bg-surface/90 px-3 backdrop-blur sm:px-4">
          <Button ref={toggleRef} variant="ghost" className="px-2" aria-label={open ? 'Close sidebar' : 'Open sidebar'} aria-expanded={open} aria-controls="app-sidebar" onClick={toggle}>
            <PanelLeft className="h-[18px] w-[18px]" strokeWidth={1.5} aria-hidden />
          </Button>
          <h1 className="min-w-0 flex-1 truncate whitespace-nowrap font-pixel text-base tracking-wide sm:text-lg" title={title}>{title}</h1>
          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            <span className="hidden text-xs text-muted md:inline">Workspace: <span className="font-medium text-fg">{user?.login}</span></span>
            <ThemeToggle />
            <ProfileMenu />
            <Button variant="secondary" size="sm" className="px-2 md:px-2.5" onClick={logout} aria-label="Sign out">
              <LogOut className="h-4 w-4" strokeWidth={1.5} aria-hidden /><span className="hidden md:inline">Sign out</span>
            </Button>
          </div>
        </header>
        <main className="mx-auto max-w-6xl p-4 sm:p-6"><Outlet /></main>
      </div>
    </div>
  )
}
