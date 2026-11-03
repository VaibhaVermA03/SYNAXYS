import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ClipboardCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Card, EmptyState, ErrorState, Pagination, Select, Skeleton, StatusBadge } from '../../components/ui'
import { PrLink, SeverityCounts } from '../../components/code-review/ReviewParts'
import { describeError } from '../../lib/api'
import { formatDate, formatDuration } from '../../lib/utils'
import { reviewService } from '../../services'

export default function ReviewsPage() {
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const params = { status, page, page_size: 20 }
  const q = useQuery({ queryKey: ['reviews', params], queryFn: () => reviewService.list(params), placeholderData: (p) => p,
    refetchInterval: (query) => (query.state.data?.items.some((i) => ['queued', 'processing'].includes(i.status)) ? 5000 : false) })
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
              </li>
            ))}
          </ul>
        )}
      </Card>
      {q.data && <Pagination page={q.data.page} pageSize={q.data.page_size} total={q.data.total} onChange={setPage} />}
    </div>
  )
}
