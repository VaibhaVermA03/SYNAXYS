import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import { usePresence } from '../../hooks/usePresence'

const SIZES = {
  md: { box: 'h-10', text: 'text-sm', row: 'py-2', closed: '2.5rem', px: 40 },
  sm: { box: 'h-8', text: 'text-xs', row: 'py-1.5', closed: '2rem', px: 32 },
}

/**
 * Accessible single-select dropdown (select-only combobox).
 * Visual rule: the trigger and its option list are ONE rounded container with exactly the trigger's width.
 * The wrapper keeps the trigger's height in the layout, so opening never moves the page; the container grows over
 * the content below (or upward when there is no room).
 */
export default function Select({ value, onChange, options, ariaLabel, placeholder = 'Select…', disabled = false, size = 'md', className }) {
  const s = SIZES[size] || SIZES.md
  const uid = useId()
  const listId = `${uid}-list`
  const optId = (i) => `${uid}-opt-${i}`
  const wrapRef = useRef(null)
  const triggerRef = useRef(null)
  const listRef = useRef(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [dropUp, setDropUp] = useState(false)
  const { mounted, shown } = usePresence(open, 200)

  const selectedIndex = useMemo(() => options.findIndex((o) => String(o.value) === String(value)), [options, value])
  const selected = selectedIndex >= 0 ? options[selectedIndex] : null

  const openList = useCallback(() => {
    if (disabled) return
    const r = wrapRef.current?.getBoundingClientRect()
    if (r && typeof window !== 'undefined') {
      const need = s.px + Math.min(options.length * 40 + 8, 248)
      setDropUp(window.innerHeight - r.top < need && r.bottom > need) // flip upward only when it fits there
    }
    setActive(selectedIndex >= 0 ? selectedIndex : 0)
    setOpen(true)
  }, [disabled, options.length, s.px, selectedIndex])

  const close = useCallback((refocus = true) => {
    setOpen(false)
    if (refocus) triggerRef.current?.focus()
  }, [])

  const choose = useCallback((i) => {
    const o = options[i]
    if (!o) return
    onChange(o.value)
    close()
  }, [options, onChange, close])

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => { if (!wrapRef.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open])

  useEffect(() => {
    if (!open) return
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }, [open, active])

  const onKeyDown = (e) => {
    if (disabled) return
    const n = options.length
    switch (e.key) {
      case 'ArrowDown': e.preventDefault(); if (open) setActive((a) => Math.min(n - 1, a + 1)); else openList(); break
      case 'ArrowUp': e.preventDefault(); if (open) setActive((a) => Math.max(0, a - 1)); else openList(); break
      case 'Home': if (open) { e.preventDefault(); setActive(0) } break
      case 'End': if (open) { e.preventDefault(); setActive(Math.max(0, n - 1)) } break
      case 'Enter':
      case ' ': e.preventDefault(); if (open) choose(active); else openList(); break
      case 'Escape': if (open) { e.preventDefault(); e.stopPropagation(); close() } break // closes only the dropdown, not a surrounding dialog
      case 'Tab': if (open) setOpen(false); break
      default:
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { // type-ahead
          const ch = e.key.toLowerCase()
          const from = open ? active + 1 : 0
          const idx = [...options.keys()].map((k) => (k + from) % n).find((k) => String(options[k].label).toLowerCase().startsWith(ch))
          if (idx !== undefined) { if (!open) openList(); setActive(idx) }
        }
    }
  }

  return (
    <div ref={wrapRef} className={cn('relative w-full', s.box, className)}>
      {mounted && (
        <div
          className={cn('absolute inset-x-0 z-[5] overflow-hidden rounded-xl border border-border bg-surface shadow-lg transition-[max-height,opacity] duration-200 ease-out',
            dropUp ? 'bottom-0 flex flex-col-reverse' : 'top-0', !shown && 'pointer-events-none')}
          style={{ maxHeight: shown ? '19rem' : s.closed, opacity: shown ? 1 : 0 }}
        >
          <div className={s.box} aria-hidden /> {/* space occupied by the real trigger button layered on top */}
          <ul ref={listRef} id={listId} role="listbox" aria-label={ariaLabel} className={cn('max-h-60 overflow-auto border-border py-1', dropUp ? 'border-b' : 'border-t')}>
            {options.length === 0 && <li role="presentation" className={cn('px-3 text-muted', s.row, s.text)}>No options</li>}
            {options.map((o, i) => {
              const isSelected = i === selectedIndex
              return (
                <li key={String(o.value)} id={optId(i)} role="option" aria-selected={isSelected} data-index={i}
                  onMouseDown={(e) => e.preventDefault()} onClick={() => choose(i)} onMouseEnter={() => setActive(i)}
                  className={cn('flex cursor-pointer items-center justify-between gap-2 px-3', s.row, s.text, i === active && 'bg-surface-2', isSelected && 'font-medium')}>
                  <span className="truncate">{o.label}</span>
                  {isSelected && <Check className="h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden />}
                </li>
              )
            })}
          </ul>
        </div>
      )}
      <button
        ref={triggerRef} type="button" role="combobox" disabled={disabled}
        aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? listId : undefined}
        aria-activedescendant={open && options.length ? optId(active) : undefined} aria-describedby={`${uid}-value`}
        onClick={() => (open ? close(false) : openList())} onKeyDown={onKeyDown} onKeyUp={(e) => { if (e.key === ' ') e.preventDefault() }}
        className={cn('relative z-[6] flex w-full items-center justify-between gap-2 rounded-xl border px-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50', s.box, s.text,
          open ? 'border-transparent bg-transparent' : 'border-border bg-surface hover:bg-surface-2')}
      >
        <span className={cn('truncate', !selected && 'text-muted')}>{selected ? selected.label : placeholder}</span>
        <ChevronDown className={cn('h-4 w-4 shrink-0 text-muted transition-transform duration-200', open && 'rotate-180')} strokeWidth={1.5} aria-hidden />
      </button>
      <span id={`${uid}-value`} className="sr-only">{selected ? `Selected: ${selected.label}` : 'Nothing selected'}</span>
    </div>
  )
}
