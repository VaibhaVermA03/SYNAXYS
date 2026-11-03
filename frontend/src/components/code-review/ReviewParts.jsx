import { Link } from 'react-router-dom'
import { Check, Circle, Loader2, XCircle } from 'lucide-react'
import { Badge, StatusBadge } from '../ui'
import FindingCard from './FindingCard'
import { CATEGORY_LABELS, CATEGORY_ORDER } from '../../lib/diff'

const SEV = ['critical', 'high', 'medium', 'low', 'info']

export function SeverityCounts({ bySeverity }) {
  const items = SEV.filter((s) => bySeverity?.[s] > 0)
  if (items.length === 0) return <span className="text-xs text-muted">No findings</span>
  return (
    <span className="flex flex-wrap gap-1" aria-label="Findings by severity">
      {items.map((s) => <Badge key={s} tone={s === 'critical' || s === 'high' ? 'danger' : s === 'medium' ? 'warn' : 'neutral'}>{bySeverity[s]} {s}</Badge>)}
    </span>
  )
}

const STEPS = ['queued', 'processing', 'completed']
export function ReviewProgress({ status }) {
  if (!status) return <span className="text-xs text-muted">Not reviewed</span>
  if (status === 'failed' || status === 'cancelled') return <span className="inline-flex items-center gap-1 text-xs text-danger"><XCircle className="h-3.5 w-3.5" aria-hidden /><StatusBadge status={status} /></span>
  const at = STEPS.indexOf(status)
  return (
    <ol className="flex items-center gap-1 text-xs" aria-label={`Review progress: ${status}`}>
      {STEPS.map((s, i) => (
        <li key={s} className={`flex items-center gap-1 ${i <= at ? 'text-fg' : 'text-muted'}`}>
          {i < at || status === 'completed' ? <Check className="h-3.5 w-3.5 text-ok" aria-hidden /> : i === at ? <Loader2 className="h-3.5 w-3.5 animate-spin text-accent-ink" aria-hidden /> : <Circle className="h-3 w-3" aria-hidden />}
          <span className="capitalize">{s}</span>{i < STEPS.length - 1 && <span className="mx-1 text-muted">→</span>}
        </li>
      ))}
    </ol>
  )
}

export function CategoryBreakdown({ byCategory }) {
  const entries = CATEGORY_ORDER.filter((c) => byCategory?.[c]).map((c) => [c, byCategory[c]])
  if (entries.length === 0) return null
  return <div className="flex flex-wrap gap-2">{entries.map(([c, n]) => <Badge key={c} tone="accent">{CATEGORY_LABELS[c]}: {n}</Badge>)}</div>
}

export function FindingGroups({ findings, renderExtra }) {
  if (!findings?.length) return <p className="text-sm text-muted">No actionable findings were reported for this review.</p>
  return (
    <div className="space-y-5">
      {CATEGORY_ORDER.map((c) => {
        const items = findings.filter((f) => f.category === c)
        return items.length === 0 ? null : (
          <section key={c} aria-labelledby={`cat-${c}`}>
            <h3 id={`cat-${c}`} className="mb-2 font-semibold">{CATEGORY_LABELS[c]} <span className="text-sm font-normal text-muted">({items.length})</span></h3>
            <div className="space-y-2">{items.map((f) => <div key={f.id}><FindingCard finding={f} />{renderExtra?.(f)}</div>)}</div>
          </section>
        )
      })}
    </div>
  )
}

export const PrLink = ({ review }) => <Link className="font-medium hover:underline" to={`/app/pull-requests/${review.pr_id}`}>{review.repository} #{review.pr_number}</Link>
