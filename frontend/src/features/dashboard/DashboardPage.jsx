import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FolderGit2, GitPullRequest, ClipboardCheck, Timer, FlaskConical, Plus, Send, XCircle } from 'lucide-react'
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton, StatusBadge } from '../../components/ui'
import { describeError } from '../../lib/api'
import { formatDate, formatDuration } from '../../lib/utils'
import { dashboardService } from '../../services'

const SEV_ORDER = ['critical', 'high', 'medium', 'low', 'info']
const SEV_BAR = { critical: 'bg-danger', high: 'bg-danger/70', medium: 'bg-warn', low: 'bg-accent', info: 'bg-muted' }

const Stat = ({ icon: Icon, label, value, hint }) => (
  <Card className="p-4">
    <div className="flex items-center gap-2 text-sm text-muted"><Icon className="h-4 w-4" aria-hidden />{label}</div>
    <div className="mt-2 text-2xl font-semibold">{value}</div>
    {hint && <div className="text-xs text-muted">{hint}</div>}
  </Card>
)

export default function DashboardPage() {
  const q = useQuery({ queryKey: ['dashboard'], queryFn: dashboardService.get })

  if (q.isPending) return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>
  if (q.isError) return <Card><ErrorState message={describeError(q.error)} onRetry={q.refetch} /></Card>
  const d = q.data

  if (d.total_repositories === 0) {
    return (
      <Card>
        <EmptyState icon={FolderGit2} title="Connect your first repository"
          description="Install the SYNAXYS GitHub App, sync your repositories, and enable reviewing on the ones you choose."
          action={<Link to="/app/repositories"><Button><Plus className="h-4 w-4" aria-hidden />Connect repositories</Button></Link>} />
      </Card>
    )
  }
  const maxSev = Math.max(1, ...SEV_ORDER.map((s) => d.findings_by_severity[s] || 0))
  const totalFindings = SEV_ORDER.reduce((n, s) => n + (d.findings_by_severity[s] || 0), 0)

  return (
    <div className="space-y-6">
      {d.has_demo_data && (
        <div className="flex items-center gap-2 rounded-lg border border-accent/40 bg-accent/10 p-3 text-sm">
          <FlaskConical className="h-4 w-4 shrink-0 text-accent-ink" aria-hidden />
          <span>Some items below are <strong>sample demo data</strong> (labelled “Demo”), not real GitHub activity.</span>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Stat icon={FolderGit2} label="Repositories" value={d.connected_repositories} hint={`${d.total_repositories} accessible`} />
        <Stat icon={GitPullRequest} label="Open PRs tracked" value={d.open_pull_requests} />
        <Stat icon={ClipboardCheck} label="Reviews completed" value={d.reviews_completed} />
        <Stat icon={Timer} label="Avg review time" value={formatDuration(d.avg_review_duration_ms)} />
        <Stat icon={Send} label="Comments published" value={d.published_comments} hint="to GitHub, after approval" />
        <Stat icon={XCircle} label="Failed reviews" value={d.failed_reviews} hint={d.failed_reviews ? 'open Code Reviews to retry' : 'none'} />
      </div>
      <Card className="p-4">
        <h2 className="font-semibold">Reviews, last 14 days</h2>
        <div className="mt-3 flex h-24 items-end gap-1" role="img" aria-label={`Reviews per day over the last 14 days: ${d.reviews_by_day.map((x) => `${x.date}: ${x.count}`).join(', ')}`}>
          {d.reviews_by_day.map((x) => (
            <div key={x.date} className="flex flex-1 flex-col items-center justify-end" title={`${x.date}: ${x.count}`}>
              <div className={`w-full rounded-t ${x.count ? 'bg-accent' : 'bg-surface-2'}`} style={{ height: `${x.count ? Math.max(8, (x.count / Math.max(1, ...d.reviews_by_day.map((y) => y.count))) * 100) : 4}%` }} />
            </div>
          ))}
        </div>
        {Object.keys(d.indexing_by_status).length > 0 && <p className="mt-3 text-xs text-muted">Code search index: {Object.entries(d.indexing_by_status).map(([k, n]) => `${n} ${k.replace('_', ' ')}`).join(' · ')}</p>}
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-4 lg:col-span-1">
          <h2 className="font-semibold">Issues by severity</h2>
          <p className="text-xs text-muted">AI-generated suggestions, not confirmed vulnerabilities.</p>
          {totalFindings === 0 ? <p className="mt-4 text-sm text-muted">No findings yet.</p> : (
            <ul className="mt-4 space-y-2">
              {SEV_ORDER.map((s) => (
                <li key={s} className="text-sm">
                  <div className="flex justify-between capitalize"><span>{s}</span><span>{d.findings_by_severity[s] || 0}</span></div>
                  <div className="mt-1 h-2 rounded-full bg-surface-2"><div className={`h-2 rounded-full ${SEV_BAR[s]}`} style={{ width: `${((d.findings_by_severity[s] || 0) / maxSev) * 100}%` }} /></div>
                </li>
              ))}
            </ul>
          )}
          <h3 className="mt-6 text-sm font-semibold">Processing status</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {Object.keys(d.reviews_by_status).length === 0 ? <span className="text-sm text-muted">No reviews yet.</span> :
              Object.entries(d.reviews_by_status).map(([s, n]) => <span key={s} className="flex items-center gap-1"><StatusBadge status={s} /><span className="text-xs text-muted">{n}</span></span>)}
          </div>
        </Card>

        <Card className="p-4 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Recent review activity</h2>
            <div className="flex gap-2">
              <Link to="/app/repositories"><Button variant="secondary" size="sm">Connect repositories</Button></Link>
              <Link to="/app/pull-requests"><Button size="sm">Review a PR</Button></Link>
            </div>
          </div>
          {d.recent_reviews.length === 0 ? <EmptyState title="No reviews yet" description="Reviews appear here when a pull request on a connected repository is reviewed." /> : (
            <ul className="mt-3 divide-y divide-border">
              {d.recent_reviews.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2 py-3 text-sm">
                  <div className="min-w-0 flex-1">
                    <Link to={`/app/reviews/${r.id}`} className="font-medium hover:underline">{r.repository} #{r.pr_number}</Link>
                    <div className="truncate text-xs text-muted">{r.pr_title} · {formatDate(r.created_at)}</div>
                  </div>
                  {r.is_demo && <Badge tone="accent">Demo</Badge>}
                  <Badge>{r.findings} findings</Badge>
                  <StatusBadge status={r.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
