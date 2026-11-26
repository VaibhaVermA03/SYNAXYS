import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, XCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Pagination, Select, Skeleton, StatusBadge } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { PrLink, SeverityCounts } from '../../components/code-review/ReviewParts'
import { describeError } from '../../lib/api'
import { formatDate, formatDuration } from '../../lib/utils'
import { reviewService } from '../../services'

export default function ReviewsPage() {
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [toCancel, setToCancel] = useState(null)
  const qc = useQueryClient()
  const { toast } = useToast()
  const params = { status, page, page_size: 20 }
  const q = useQuery({ queryKey: ['reviews', params], queryFn: () => reviewService.list(params), placeholderData: (p) => p,
    refetchInterval: (query) => (query.state.data?.items.some((i) => ['queued', 'processing'].includes(i.status)) ? 5000 : false) })
  const cancel = useMutation({
    mutationFn: (id) => reviewService.cancel(id),
    onSuccess: () => toast('Review cancelled. It will not run.', 'success'),
    onError: (e) => toast(describeError(e), 'error'),  // e.g. "already started"
    onSettled: () => { setToCancel(null); qc.invalidateQueries({ queryKey: ['reviews'] }) },
  })
  return (
    <div className="space-y-4">
      <Select ariaLabel="Status" className="sm:w-56" value={status} onChange={(v) => { setStatus(v); setPage(1) }}
        options={[{ value: '', label: 'Any status' }, { value: 'queued', label: 'Queued' }, { value: 'processing', label: 'Processing' }, { value: 'completed', label: 'Completed' },
          { value: 'failed', label: 'Failed' }, { value: 'cancelled', label: 'Cancelled' }]} />
      <Card>
        {q.isPending && <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}</div>}
        {q.isError && <ErrorState message={describeError(q.error)} onRetry={q.refetch} />}
        {q.data?.items.length === 0 && <EmptyState icon={ClipboardCheck} title="No reviews yet" description="Reviews appear here when a pull request on a connected repository is reviewed." />}
        {q.data?.items.length > 0 && (
          <ul className="divide-y divide-border">
            {q.data.items.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 p-4 text-sm">
                <div className="min-w-0 flex-1">
                  <Link to={`/app/reviews/${r.id}`} className="font-medium hover:underline">Review #{r.id}</Link> · <PrLink review={r} />
                  <div className="truncate text-xs text-muted">{r.pr_title} · {formatDate(r.created_at)} · {formatDuration(r.duration_ms)}</div>
                </div>
                {r.is_demo && <Badge tone="accent">Demo</Badge>}
                <SeverityCounts bySeverity={r.by_severity} /><StatusBadge status={r.status} />
                {r.status === 'queued' && !r.is_demo && <Button size="sm" variant="ghost" onClick={() => setToCancel(r)}><XCircle className="h-4 w-4" aria-hidden />Cancel</Button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {q.data && <Pagination page={q.data.page} pageSize={q.data.page_size} total={q.data.total} onChange={setPage} />}
      <ConfirmDialog open={!!toCancel} danger title={`Cancel review #${toCancel?.id}?`} confirmLabel="Cancel review" loading={cancel.isPending}
        description="The review is removed from the queue and will not run. This only works while it is still waiting; nothing is posted to GitHub. You can retry it later."
        onCancel={() => setToCancel(null)} onConfirm={() => cancel.mutate(toCancel.id)} />
    </div>
  )
}
