import { Link, useParams } from 'react-router-dom'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCheck, RotateCcw, Send } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, ErrorState, Skeleton, StatusBadge } from '../../components/ui'
import CommentActions from '../../components/code-review/CommentActions'
import { useToast } from '../../components/ui/Toast'
import { CategoryBreakdown, FindingGroups, PrLink, SeverityCounts } from '../../components/code-review/ReviewParts'
import { describeError } from '../../lib/api'
import { formatDate, formatDuration } from '../../lib/utils'
import { reviewService } from '../../services'

const BLOCKERS = {
  review_stale: 'The pull request changed after this review, so line numbers may no longer match. Run a new review before publishing.',
  demo_readonly: 'Demo reviews are sample data and can never be published.',
  repository_not_connected: 'Connect this repository before publishing.',
  pr_not_open: 'The pull request is no longer open.',
  github_app_not_configured: 'The GitHub App is not configured on this server, so publishing is unavailable.',
  review_not_completed: 'Only completed reviews can be published.',
}

export default function ReviewDetailPage() {
  const { reviewId } = useParams()
  const qc = useQueryClient()
  const { toast } = useToast()
  const q = useQuery({ queryKey: ['review', reviewId], queryFn: () => reviewService.get(reviewId),
    refetchInterval: (query) => (['queued', 'processing'].includes(query.state.data?.status) ? 4000 : false) })
  const [confirmPublish, setConfirmPublish] = useState(false)
  const attempts = useQuery({ queryKey: ['review-attempts', reviewId], queryFn: () => reviewService.attempts(reviewId) })
  const refreshAll = () => { qc.invalidateQueries({ queryKey: ['review', reviewId] }); qc.invalidateQueries({ queryKey: ['review-attempts', reviewId] }); qc.invalidateQueries({ queryKey: ['reviews'] }) }
  const approveAll = useMutation({ mutationFn: () => reviewService.approve(reviewId, null), onSuccess: (r) => { toast(`${r.approved} comment(s) approved.`, 'success'); refreshAll() }, onError: (e) => toast(describeError(e), 'error') })
  const publish = useMutation({
    mutationFn: () => reviewService.publish(reviewId),
    onSuccess: (r) => { setConfirmPublish(false); toast(`Published ${r.posted} comment(s) to GitHub${r.skipped_existing ? ` (${r.skipped_existing} already there)` : ''}${r.failed ? `, ${r.failed} rejected by GitHub` : ''}.`, r.failed ? 'info' : 'success'); refreshAll() },
    onError: (e) => { setConfirmPublish(false); toast(describeError(e), 'error'); refreshAll() },
  })
  const retry = useMutation({
    mutationFn: () => reviewService.retry(reviewId),
    onSuccess: () => { toast('Retry queued.', 'success'); qc.invalidateQueries({ queryKey: ['review', reviewId] }); qc.invalidateQueries({ queryKey: ['reviews'] }) },
    onError: (e) => toast(describeError(e), 'error'),
  })
  if (q.isPending) return <Skeleton className="h-48" />
  if (q.isError) return <Card><ErrorState message={q.error.status === 404 ? 'Review not found.' : describeError(q.error)} onRetry={q.refetch} /></Card>
  const r = q.data
  const drafts = r.findings_list.filter((f) => f.comment?.state === 'draft').length
  return (
    <div className="space-y-4">
      <Link to="/app/reviews" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ArrowLeft className="h-4 w-4" aria-hidden />Reviews</Link>
      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Review #{r.id}</h2><StatusBadge status={r.status} />
          {r.is_demo && <Badge tone="accent">Sample fixture — no AI was run</Badge>}
          <span className="text-sm text-muted"><PrLink review={r} /> · {r.pr_title}</span>
        </div>
        <p className="text-xs text-muted">Created {formatDate(r.created_at)} · {formatDuration(r.duration_ms)}{r.model ? ` · model: ${r.model}` : ''} · head {r.head_sha.slice(0, 7)}</p>
        <p className="text-xs text-muted">AI-generated suggestions, not confirmed vulnerabilities. They do not replace deterministic scanners or human review.</p>
        {r.status === 'failed' && (
          <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm">
            <span>Review failed{r.error ? `: ${r.error}` : '.'}</span>
            {r.can_retry && <Button size="sm" variant="secondary" loading={retry.isPending} onClick={() => retry.mutate()}><RotateCcw className="h-4 w-4" aria-hidden />Retry review</Button>}
          </div>
        )}
        {r.summary && <p className="text-sm">{r.summary}</p>}
        <div className="flex flex-wrap items-center gap-3"><SeverityCounts bySeverity={r.by_severity} /><CategoryBreakdown byCategory={r.by_category} /></div>
        <p className="text-xs text-muted">Policy: {r.require_approval ? 'comments need explicit approval by a repository admin before publishing' : 'approval not required'}{r.auto_publish ? ' · auto-publish enabled by a repository admin' : ''}. Published reviews are posted as a plain comment review — SYNAXYS never approves or requests changes.</p>
        {r.status === 'completed' && !r.is_demo && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border p-3 text-sm" role="group" aria-label="Publishing">
            <span>{drafts} draft · {r.approved_comments} approved</span>
            {r.can_manage && drafts > 0 && <Button size="sm" variant="secondary" loading={approveAll.isPending} onClick={() => approveAll.mutate()}><CheckCheck className="h-4 w-4" aria-hidden />Approve all drafts</Button>}
            {r.publishable && <Button size="sm" onClick={() => setConfirmPublish(true)}><Send className="h-4 w-4" aria-hidden />Publish {r.approved_comments} approved comment{r.approved_comments === 1 ? '' : 's'}</Button>}
            {!r.can_manage && <span className="text-xs text-muted">Only repository admins can approve and publish.</span>}
            {r.can_manage && r.publish_blocker && (drafts > 0 || r.approved_comments > 0) && <p role="status" className="basis-full text-xs text-warn">{BLOCKERS[r.publish_blocker] || 'Publishing is currently unavailable.'}</p>}
          </div>
        )}
      </Card>
      {['queued', 'processing'].includes(r.status) ? <Card><p className="p-4 text-sm text-muted">This review is {r.status}. Results will appear automatically.</p></Card>
        : <Card className="p-4"><FindingGroups findings={r.findings_list} renderExtra={(f) => (f.comment ? <CommentActions reviewId={r.id} comment={f.comment} canManage={r.can_manage} /> : null)} /></Card>}
      {attempts.data?.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-2 font-semibold">Publishing history</h3>
          <ul className="space-y-1 text-xs">
            {attempts.data.map((a) => (
              <li key={a.id} className="flex flex-wrap gap-2"><Badge tone={a.status === 'success' ? 'ok' : a.status === 'failed' ? 'danger' : 'neutral'}>{a.status}</Badge>
                <span>{formatDate(a.created_at)}</span><span className="text-muted">{a.actor || 'system'}{a.http_status ? ` · HTTP ${a.http_status}` : ''}{a.error ? ` · ${a.error}` : ''}</span></li>
            ))}
          </ul>
        </Card>
      )}
      <ConfirmDialog open={confirmPublish} title="Publish to GitHub?" confirmLabel="Publish" loading={publish.isPending}
        description={`This posts ${r.approved_comments} approved comment(s) and the review summary on the pull request as a comment-only review. They will be visible to everyone with access to the repository and cannot be unpublished from SYNAXYS.`}
        onCancel={() => setConfirmPublish(false)} onConfirm={() => publish.mutate()} />
    </div>
  )
}
