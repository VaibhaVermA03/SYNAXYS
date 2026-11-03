import { forwardRef, useEffect, useRef } from 'react'
import { AlertTriangle, Inbox, Loader2, ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '../../lib/utils'

export { default as Select } from './Select'
export { default as Tooltip } from './Tooltip'

const VARIANTS = {
  primary: 'bg-accent text-accent-fg hover:opacity-90',
  secondary: 'border border-border bg-surface hover:bg-surface-2',
  danger: 'bg-danger text-danger-fg hover:opacity-90',
  ghost: 'hover:bg-surface-2',
}

export const Button = forwardRef(function Button({ variant = 'primary', size = 'md', loading, className, children, disabled, ...p }, ref) {
  return (
    <button ref={ref} disabled={disabled || loading} aria-busy={loading || undefined}
      className={cn('inline-flex items-center justify-center gap-2 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-3.5 py-2 text-sm', VARIANTS[variant], className)} {...p}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
})

export const Card = ({ className, ...p }) => <div className={cn('rounded-xl border border-border bg-surface', className)} {...p} />

export const Input = forwardRef(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn('w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm placeholder:text-muted', className)} {...p} />
})

export const Badge = ({ tone = 'neutral', className, ...p }) => {
  const tones = {
    neutral: 'bg-surface-2 text-fg', ok: 'bg-ok/10 text-ok', warn: 'bg-warn/10 text-warn',
    danger: 'bg-danger/10 text-danger', accent: 'bg-accent/10 text-accent-ink',
  }
  return <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', tones[tone], className)} {...p} />
}

export const Skeleton = ({ className }) => <div aria-hidden className={cn('animate-pulse rounded-md bg-surface-2', className)} />

export function EmptyState({ title, description, action, icon: Icon = Inbox }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <Icon className="h-8 w-8 text-muted" aria-hidden />
      <h3 className="font-semibold">{title}</h3>
      {description && <p className="max-w-md text-sm text-muted">{description}</p>}
      {action}
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-10 text-center">
      <AlertTriangle className="h-8 w-8 text-danger" aria-hidden />
      <p className="max-w-md text-sm">{message || 'Something went wrong.'}</p>
      {onRetry && <Button variant="secondary" onClick={onRetry}>Try again</Button>}
    </div>
  )
}

export function Pagination({ page, pageSize, total, onChange }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (total <= pageSize) return null
  return (
    <nav className="flex items-center justify-between pt-3 text-sm" aria-label="Pagination">
      <span className="text-muted">Page {page} of {pages} · {total} total</span>
      <div className="flex gap-2">
        <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button>
        <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button>
      </div>
    </nav>
  )
}

export function ConfirmDialog({ open, title, description, confirmLabel = 'Confirm', danger, loading, onConfirm, onCancel }) {
  const cancelRef = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    cancelRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onCancel])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="w-full max-w-md rounded-xl border border-border bg-surface p-5 shadow-xl">
        <h2 id="confirm-title" className="text-lg font-semibold">{title}</h2>
        <p className="mt-2 text-sm text-muted">{description}</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button ref={cancelRef} variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button variant={danger ? 'danger' : 'primary'} loading={loading} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  )
}

const SEV = { critical: 'danger', high: 'danger', medium: 'warn', low: 'accent', info: 'neutral' }
export const SeverityBadge = ({ severity }) => <Badge tone={SEV[severity] || 'neutral'} className="capitalize">{severity}</Badge>

const STATUS = { queued: 'neutral', processing: 'accent', completed: 'ok', succeeded: 'ok', failed: 'danger', cancelled: 'neutral' }
export const StatusBadge = ({ status }) => <Badge tone={STATUS[status] || 'neutral'} className="capitalize">{status}</Badge>
