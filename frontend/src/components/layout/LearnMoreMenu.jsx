import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { BookOpen, ChevronRight } from 'lucide-react'
import { LEGAL_LINKS } from '../../features/legal/LegalFooter'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { cn } from '../../lib/utils'

const ITEM = 'block rounded-lg px-3 py-2 font-pixel text-[13px] tracking-wide text-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:bg-surface-2 focus-visible:text-fg'

/**
 * Sidebar entry "Learn more" with the four legal pages.
 * Desktop: hovering (or focusing / pressing Enter on) the entry opens a small popup next to the sidebar; it is drawn in a portal so the
 *          sidebar's scroll container cannot clip it. Escape, moving the pointer away, tabbing away or clicking elsewhere closes it.
 * Mobile / touch-width: there is no hover, so the entry expands in place and the button toggles it.
 */
export default function LearnMoreMenu({ sidebarOpen = true, onNavigate }) {
  const isDesktop = useMediaQuery('(min-width: 1024px)')
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)
  const wrapRef = useRef(null)
  const btnRef = useRef(null)
  const flyRef = useRef(null)
  const timer = useRef(null)

  const cancelClose = useCallback(() => { if (timer.current) { clearTimeout(timer.current); timer.current = null } }, [])
  const close = useCallback(() => { cancelClose(); setOpen(false) }, [cancelClose])
  const scheduleClose = () => { cancelClose(); timer.current = setTimeout(() => setOpen(false), 150) } // short grace so the pointer can cross the gap to the popup
  useEffect(() => cancelClose, [cancelClose])
  useEffect(() => { if (!sidebarOpen) close() }, [sidebarOpen, close])

  // Place the desktop popup just right of the sidebar, level with the entry, kept inside the viewport.
  useLayoutEffect(() => {
    if (!open || !isDesktop || !btnRef.current) { setPos(null); return }
    const btn = btnRef.current.getBoundingClientRect()
    const side = btnRef.current.closest('aside')?.getBoundingClientRect()
    const h = flyRef.current?.offsetHeight || 0
    setPos({ left: (side?.right ?? btn.right) + 6, top: Math.max(8, Math.min(btn.top, window.innerHeight - h - 8)) })
  }, [open, isDesktop])

  // Click / tap anywhere else closes it (touch screens at desktop width never "leave" the entry).
  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => { if (!wrapRef.current?.contains(e.target) && !flyRef.current?.contains(e.target)) close() }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open, close])

  const onKeyDown = (e) => { if (e.key === 'Escape' && open) { e.stopPropagation(); close(); btnRef.current?.focus() } }
  const onBlur = (e) => {
    const next = e.relatedTarget
    if (next && (wrapRef.current?.contains(next) || flyRef.current?.contains(next))) return
    if (isDesktop) close()
  }
  const go = () => { close(); onNavigate?.() }

  const links = (
    <ul aria-label="Learn more" className="space-y-0.5">
      {LEGAL_LINKS.map(([to, label]) => <li key={to}><Link to={to} className={ITEM} onClick={go}>{label}</Link></li>)}
    </ul>
  )

  return (
    <div
      ref={wrapRef} onKeyDown={onKeyDown} onBlur={onBlur}
      onMouseEnter={() => { if (isDesktop) { cancelClose(); setOpen(true) } }}
      onMouseLeave={() => { if (isDesktop) scheduleClose() }}
    >
      <button
        ref={btnRef} type="button" aria-expanded={open} aria-haspopup="true"
        onClick={() => (isDesktop ? setOpen(true) : setOpen((o) => !o))}
        className={cn('flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left font-pixel text-[13px] tracking-wide transition-colors',
          open ? 'bg-surface-2 text-fg' : 'text-muted hover:bg-surface-2 hover:text-fg')}
      >
        <BookOpen className="h-[18px] w-[18px] shrink-0" strokeWidth={1.5} aria-hidden />
        <span className="flex-1">Learn more</span>
        <ChevronRight className={cn('h-4 w-4 shrink-0 transition-transform', !isDesktop && open && 'rotate-90')} strokeWidth={1.5} aria-hidden />
      </button>

      {open && !isDesktop && <div className="ml-7 mt-0.5 border-l border-border pl-2">{links}</div>}

      {open && isDesktop && createPortal(
        <div
          ref={flyRef} onMouseEnter={cancelClose} onMouseLeave={scheduleClose} onKeyDown={onKeyDown} onBlur={onBlur}
          style={{ position: 'fixed', left: pos?.left ?? 0, top: pos?.top ?? 0, visibility: pos ? 'visible' : 'hidden' }}
          className="z-50 w-52 rounded-xl border border-border bg-surface p-1.5 shadow-xl"
        >
          {links}
        </div>,
        document.body,
      )}
    </div>
  )
}