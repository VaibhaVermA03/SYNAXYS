import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ExternalLink, FlaskConical, Play, RotateCcw } from 'lucide-react'
import { Badge, Button, Card, ErrorState, Select, Skeleton, StatusBadge } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import DiffViewer from '../../components/code-review/DiffViewer'
import FileTree from '../../components/code-review/FileTree'
import { CategoryBreakdown, FindingGroups, ReviewProgress, SeverityCounts } from '../../components/code-review/ReviewParts'
import { describeError } from '../../lib/api'
import { fileAnchor } from '../../lib/diff'
import { formatDate, formatDuration } from '../../lib/utils'
import { pullRequestService, reviewService } from '../../services'

export default function PullRequestDetailPage() {
  const { pullRequestId } = useParams()
  const qc = useQueryClient()
  const { toast } = useToast()
  const [reviewId, setReviewId] = useState(null)
  const [active, setActive] = useState(null)

  const pr = useQuery({ queryKey: ['pull-request', pullRequestId], queryFn: () => pullRequestService.get(pullRequestId),
    refetchInterval: (q) => (['queued', 'processing'].includes(q.state.data?.review?.status) ? 4000 : false) })
  const diff = useQuery({ queryKey: ['pull-request-diff', pullRequestId], queryFn: () => pullRequestService.diff(pullRequestId), retry: false })
  const shownId = reviewId ?? pr.data?.review?.id
  const review = useQuery({ queryKey: ['review', shownId], queryFn: () => reviewService.get(shownId), enabled: !!shownId })

  const refresh = () => { qc.invalidateQueries({ queryKey: ['pull-request', pullRequestId] }); qc.invalidateQueries({ queryKey: ['review'] }); qc.invalidateQueries({ queryKey: ['pull-requests'] }) }
  const run = useMutation({ mutationFn: () => pullRequestService.requestReview(pullRequestId), onSuccess: (r) => { setReviewId(r.id); toast('Review queued.', 'success'); refresh() }, onError: (e) => toast(describeError(e), 'error') })
  const retry = useMutation({ mutationFn: () => reviewService.retry(shownId), onSuccess: () => { toast('Retry queued.', 'success'); refresh() }, onError: (e) => toast(describeError(e), 'error') })

  if (pr.isPending) return <Skeleton className="h-40" />
  if (pr.isError) return <Card><ErrorState message={pr.error.status === 404 ? 'Pull request not found.' : describeError(pr.error)} onRetry={pr.refetch} /></Card>
  const p = pr.data
  const rv = review.data
  const findings = rv?.findings_list || []
  const select = (path) => { setActive(path); document.getElementById(fileAnchor(path))?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }

  return (
    <div className="space-y-4">
      <Link to="/app/pull-requests" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ArrowLeft className="h-4 w-4" aria-hidden />Pull requests</Link>
      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold">{p.title} <span className="font-normal text-muted">#{p.number}</span></h2>
            <p className="text-sm text-muted">{p.repository} · by {p.author} · {p.head_branch} → {p.base_branch} · updated {formatDate(p.updated_at)}</p>
          </div>
          <Badge tone={p.state === 'open' ? 'ok' : p.state === 'merged' ? 'accent' : 'neutral'} className="capitalize">{p.state}</Badge>
          {p.is_demo && <Badge tone="accent"><FlaskConical className="mr-1 h-3 w-3" aria-hidden />Demo data</Badge>}
          {p.html_url && <a href={p.html_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-accent-ink hover:underline">View on GitHub<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ReviewProgress status={p.review?.status} />
          {p.can_request_review
            ? <Button size="sm" loading={run.isPending} onClick={() => run.mutate()}><Play className="h-4 w-4" aria-hidden />{p.review ? 'Run a new review' : 'Review this PR'}</Button>
            : <span className="text-xs text-muted">{p.is_demo ? 'Demo pull requests are read-only sample data.' : !p.repo_enabled ? 'Connect this repository to request reviews.' : 'Only open pull requests can be reviewed.'}</span>}
          {p.reviews.length > 1 && (
            <Select size="sm" ariaLabel="Review history" className="sm:w-72" value={shownId || ''} onChange={(v) => setReviewId(Number(v))}
              options={p.reviews.map((r) => ({ value: r.id, label: `#${r.id} · ${r.status} · ${formatDate(r.created_at)}` }))} />
          )}
        </div>
      </Card>

      {rv && (
        <Card className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="font-semibold">Review #{rv.id}</h3><StatusBadge status={rv.status} />
            <span className="text-xs text-muted">{formatDuration(rv.duration_ms)}{rv.model ? ` · ${rv.model}` : ''}</span>
            {rv.is_demo && <Badge tone="accent">Sample fixture — no AI was run</Badge>}
            <Link className="ml-auto text-sm text-accent-ink hover:underline" to={`/app/reviews/${rv.id}`}>Open full review</Link>
          </div>
          <p className="text-xs text-muted">Findings are AI-generated suggestions. They are not confirmed vulnerabilities and do not replace deterministic scanners or human review.</p>
          {rv.status === 'failed' && (
            <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm">
              <span>Review failed{rv.error ? `: ${rv.error}` : '.'}</span>
              {rv.can_retry && <Button size="sm" variant="secondary" loading={retry.isPending} onClick={() => retry.mutate()}><RotateCcw className="h-4 w-4" aria-hidden />Retry</Button>}
            </div>
          )}
          {rv.summary && <p className="text-sm">{rv.summary}</p>}
          <div className="flex flex-wrap items-center gap-3"><SeverityCounts bySeverity={rv.by_severity} /><CategoryBreakdown byCategory={rv.by_category} /></div>
          <p className="text-xs text-muted">Comments are drafts kept in SYNAXYS. Publishing to GitHub is not available in this build.</p>
        </Card>
      )}

      {diff.isPending && <Skeleton className="h-64" />}
      {diff.isError && <Card><ErrorState message={describeError(diff.error)} onRetry={diff.refetch} /></Card>}
      {diff.data && (
        <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
          <Card className="h-fit p-2 lg:sticky lg:top-16"><FileTree files={diff.data.files} findings={findings} active={active} onSelect={select} /></Card>
          <div className="min-w-0 space-y-3">
            {diff.data.omitted_files > 0 && <p role="status" className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm">{diff.data.omitted_files} more changed file(s) exceed the configured limit and are not shown or reviewed.</p>}
            {diff.data.files.length === 0 ? <Card><p className="p-4 text-sm text-muted">This pull request has no changed files.</p></Card> : <DiffViewer files={diff.data.files} findings={findings} />}
          </div>
        </div>
      )}

      {rv && findings.length > 0 && (
        <Card className="p-4"><h3 className="mb-3 text-lg font-semibold">All findings</h3><FindingGroups findings={findings} /></Card>
      )}
    </div>
  )
}
