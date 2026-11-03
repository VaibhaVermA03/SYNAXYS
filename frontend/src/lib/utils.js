import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export const cn = (...a) => twMerge(clsx(a))

export function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatDuration(ms) {
  if (ms == null) return '—'
  return ms < 1000 ? `${ms} ms` : ms < 60000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 60000)} min`
}
