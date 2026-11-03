import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { GitBranch, GitPullRequest, Search } from 'lucide-react'
import { Badge, Card, EmptyState, ErrorState, Input, Pagination, Select, Skeleton } from '../../components/ui'
import { ReviewProgress, SeverityCounts } from '../../components/code-review/ReviewParts'
import { describeError } from '../../lib/api'
import { formatDate } from '../../lib/utils'
import { githubService, pullRequestService } from '../../services'

const STATE_TONE = { open: 'ok', merged: 'accent', closed: 'neutral' }
const STATE_OPTIONS = [{ value: '', label: 'Any state' }, { value: 'open', label: 'Open' }, { value: 'closed', label: 'Closed' }, { value: 'merged', label: 'Merged' }]
const REVIEW_OPTIONS = [{ value: '', label: 'Any review status' }, { value: 'none', label: 'Not reviewed' }, { value: 'queued', label: 'Queued' }, { value: 'processing', label: 'Processing' },
  { value: 'completed', label: 'Completed' }, { value: 'failed', label: 'Failed' }]
const SORT_OPTIONS = [{ value: 'updated:desc', label: 'Recently updated' }, { value: 'updated:asc', label: 'Least recently updated' }, { value: 'number:desc', label: 'Number (high → low)' }, { value: 'number:asc', label: 'Number (low → high)' }]

function useDebounced(v, ms = 300) {
  const [d, setD] = useState(v)
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t) }, [v, ms])
  return d
}

export default function PullRequestsPage() {
  const [f, setF] = useState({ search: '', state: '', review_status: '', repository_id: '', sort: 'updated', order: 'desc', page: 1 })
  const set = (patch) => setF((x) => ({ ...x, page: 1, ...patch }))
  const q = useDebounced(f.search)
  const params = { q, state: f.state, review_status: f.review_status, repository_id: f.repository_id, sort: f.sort, order: f.order, page: f.page, page_size: 20 }
  const prs = useQuery({ queryKey: ['pull-requests', params], queryFn: () => pullRequestService.list(params), placeholderData: (p) => p, refetchInterval: (query) => (query.state.data?.items.some((i) => ['queued', 'processing'].includes(i.review?.status)) ? 5000 : false) })
  const repos = useQuery({ queryKey: ['repositories', 'all-for-filter'], queryFn: () => githubService.repositories({ page_size: 100 }) })
  const filtered = !!(q || f.state || f.review_status || f.repository_id)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden />
          <Input className="pl-9" placeholder="Search title, author or repository…" aria-label="Search pull requests" value={f.search} onChange={(e) => setF((x) => ({ ...x, search: e.target.value, page: 1 }))} />
        </div>
        <Select ariaLabel="Repository" className="sm:w-52" value={f.repository_id} onChange={(v) => set({ repository_id: v })}
          options={[{ value: '', label: 'All repositories' }, ...(repos.data?.items || []).map((r) => ({ value: String(r.id), label: r.full_name }))]} />
        <Select ariaLabel="State" className="sm:w-40" value={f.state} onChange={(v) => set({ state: v })} options={STATE_OPTIONS} />
        <Select ariaLabel="Review status" className="sm:w-48" value={f.review_status} onChange={(v) => set({ review_status: v })} options={REVIEW_OPTIONS} />
        <Select ariaLabel="Sort" className="sm:w-52" value={`${f.sort}:${f.order}`} onChange={(v) => { const [sort, order] = v.split(':'); set({ sort, order }) }} options={SORT_OPTIONS} />
      </div>

      <Card>
        {prs.isPending && <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div>}
        {prs.isError && <ErrorState message={describeError(prs.error)} onRetry={prs.refetch} />}
        {prs.data && prs.data.items.length === 0 && (
          <EmptyState icon={GitPullRequest} title={filtered ? 'No pull requests match' : 'No pull requests tracked yet'}
            description={filtered ? 'Try different filters.' : 'Pull requests appear here after you connect a repository and GitHub sends a pull request event.'} />
        )}
        {prs.data?.items.length > 0 && (
          <ul className="divide-y divide-border">
            {prs.data.items.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link to={`/app/pull-requests/${p.id}`} className="font-medium hover:underline">{p.title}</Link>
                    <Badge tone={STATE_TONE[p.state]} className="capitalize">{p.state}</Badge>
                    {p.is_demo && <Badge tone="accent">Demo</Badge>}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                    <span>{p.repository} #{p.number}</span><span>by {p.author}</span>
                    <span className="inline-flex items-center gap-1"><GitBranch className="h-3 w-3" aria-hidden />{p.head_branch} → {p.base_branch}</span>
                    <span>Updated {formatDate(p.updated_at)}</span>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <ReviewProgress status={p.review?.status} />
                  {p.review?.status === 'completed' && <SeverityCounts bySeverity={p.review.by_severity} />}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {prs.data && <Pagination page={prs.data.page} pageSize={prs.data.page_size} total={prs.data.total} onChange={(page) => setF((x) => ({ ...x, page }))} />}
    </div>
  )
}
