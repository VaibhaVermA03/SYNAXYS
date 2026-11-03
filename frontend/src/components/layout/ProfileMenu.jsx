import { useEffect, useId, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { CircleUserRound, Settings } from 'lucide-react'
import { useAuth } from '../../app/AuthProvider'
import { usePresence } from '../../hooks/usePresence'
import { cn } from '../../lib/utils'

/** Profile button in the header. Click opens a small popup below it with a link to Settings (desktop and mobile). */
export default function ProfileMenu() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const [avatarFailed, setAvatarFailed] = useState(false)
  const { mounted, shown } = usePresence(open, 160)
  const wrapRef = useRef(null)
  const buttonRef = useRef(null)
  const itemRef = useRef(null)
  const menuId = useId()

  useEffect(() => { setOpen(false) }, [pathname])

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => { if (!wrapRef.current?.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') { setOpen(false); buttonRef.current?.focus() } }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('pointerdown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  useEffect(() => { if (open && mounted) itemRef.current?.focus() }, [open, mounted])

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={buttonRef} type="button" aria-label="Open profile menu" aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
        className={cn('inline-flex h-9 w-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-fg', open && 'bg-surface-2 text-fg')}
      >
        {user?.avatar_url && !avatarFailed
          ? <img src={user.avatar_url} alt="" className="h-7 w-7 rounded-full object-cover" onError={() => setAvatarFailed(true)} />
          : <CircleUserRound className="h-[22px] w-[22px]" strokeWidth={1.5} aria-hidden />}
      </button>
      {mounted && (
        <div
          id={menuId} role="menu" aria-label="Profile"
          className={cn('absolute right-0 top-full z-50 mt-2 w-56 max-w-[calc(100vw-1.5rem)] origin-top-right rounded-xl border border-border bg-surface p-1.5 shadow-lg transition duration-150 ease-out',
            shown ? 'scale-100 opacity-100' : 'pointer-events-none scale-95 opacity-0')}
        >
          <div className="px-2.5 py-2">
            <p className="truncate text-sm font-medium">{user?.name || user?.login}</p>
            <p className="truncate text-xs text-muted">@{user?.login}</p>
          </div>
          <div className="my-1 h-px bg-border" role="separator" />
          <Link ref={itemRef} to="/app/settings" role="menuitem" onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors hover:bg-surface-2 focus:bg-surface-2">
            <Settings className="h-4 w-4" strokeWidth={1.5} aria-hidden />Settings
          </Link>
        </div>
      )}
    </div>
  )
}
