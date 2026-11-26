import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Pagination, Select, Skeleton, StatusBadge } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { useAuth } from '../../app/AuthProvider'
import { describeError } from '../../lib/api'
import { formatDate } from '../../lib/utils'
import { adminService } from '../../services'
import NotFoundPage from '../../pages/NotFoundPage'

const STATUSES = [{ value: 'failed', label: 'Failed' }, { value: 'queued', label: 'Queued' }, { value: 'processing', label: 'Processing' },
  { value: 'succeeded', label: 'Succeeded' }, { value: 'cancelled', label: 'Cancelled' }, { value: '', label: 'Any status' }]
const KINDS = [{ value: '', label: 'Any type' }, { value: 'review', label: 'Review' }, { value: 'publish', label: 'Publish' },
  { value: 'index', label: 'Index' }, { value: 'index_delete', label: 'Index cleanup' }]

function Stat({ label, value, tone }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 font-pixel text-2xl ${tone === 'danger' && value > 0 ? 'text-danger' : ''}`}>{value ?? '–'}</div>
    </Card>
  )
}

function age(seconds) {
  if (seconds == null) return '–'
  if (seconds < 90) return `${seconds}s`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`
  return `${Math.round(seconds / 3600)} h`
}

function JobDetail({ id }) {
  const q = useQuery({ queryKey: ['admin-job', id], queryFn: () => adminService.job(id) })
  if (q.isPending) return <Skeleton className="m-4 h-20" />
  if (q.isError) return <ErrorState message={describeError(q.error)} onRetry={q.refetch} />
  const j = q.data
  const rows = [['Timeout', `${j.timeout_seconds}s`], ['Run after', formatDate(j.run_after)], ['Locked by', j.locked_by || '–'], ['Locked at', j.locked_at ? formatDate(j.locked_at) : '–'],
    ['Review status', j.review_status || '–'], ['Workspace', j.workspace || '–'], ['Payload (ids only)', Object.keys(j.payload).length ? JSON.stringify(j.payload) : '–']]
  return (
    <dl className="grid gap-x-6 gap-y-1 bg-surface-2/50 px-4 py-3 text-xs sm:grid-cols-2">
      {rows.map(([k, v]) => <div key={k} className="flex gap-2"><dt className="w-36 shrink-0 text-muted">{k}</dt><dd className="min-w-0 break-words">{v}</dd></div>)}
      {j.error && <div className="sm:col-span-2"><dt className="text-muted">Error summary</dt><dd className="mt-0.5 break-words">{j.error}</dd></div>}
    </dl>
  )
}

export default function AdminJobsPage() {
  const { isAdmin } = useAuth()
  const { toast } = useToast()
  const qc = useQueryClient()
  const [status, setStatus] = useState('failed')
  const [kind, setKind] = useState('')
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const params = { status, kind, page, page_size: 20 }
  const list = useQuery({ queryKey: ['admin-jobs', params], queryFn: () => adminService.jobs(params), placeholderData: (p) => p, enabled: isAdmin })
  const stats = useQuery({ queryKey: ['admin-jobs-summary'], queryFn: adminService.summary, refetchInterval: 15000, enabled: isAdmin })
  const retry = useMutation({
    mutationFn: (id) => adminService.retry(id),
    onSuccess: (_, id) => { toast(`Job #${id} re-queued`, 'success'); qc.invalidateQueries({ queryKey: ['admin-jobs'] }); qc.invalidateQueries({ queryKey: ['admin-jobs-summary'] }); qc.invalidateQueries({ queryKey: ['admin-job', id] }) },
    onError: (e) => { toast(describeError(e), 'error'); qc.invalidateQueries({ queryKey: ['admin-jobs'] }) },
    onSettled: () => setConfirm(null),
  })
  if (!isAdmin) return <NotFoundPage /> // the API enforces this too; this only avoids showing a broken screen
  const s = stats.data
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Failed (total)" value={s?.by_status.failed} tone="danger" />
        <Stat label="Failed, last 24 h" value={s?.failed_last_24h} tone="danger" />
        <Stat label="Queued" value={s?.by_status.queued} />
        <Stat label="Oldest queued" value={age(s?.queued_oldest_age_seconds)} />
        <Stat label="Stalled processing" value={s?.stale_processing} tone="danger" />
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Select ariaLabel="Status" className="sm:w-48" value={status} onChange={(v) => { setStatus(v); setPage(1); setOpen(null) }} options={STATUSES} />
        <Select ariaLabel="Job type" className="sm:w-48" value={kind} onChange={(v) => { setKind(v); setPage(1); setOpen(null) }} options={KINDS} />
      </div>
      <Card>
        {list.isPending && <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}</div>}
        {list.isError && <ErrorState message={describeError(list.error)} onRetry={list.refetch} />}
        {list.data?.items.length === 0 && <EmptyState title="No jobs match" description="Nothing found for these filters." />}
        {list.data?.items.length > 0 && (
          <ul className="divide-y divide-border">
            {list.data.items.map((j) => (
              <li key={j.id}>
                <div className="flex flex-wrap items-center gap-3 p-4 text-sm">
                  <button type="button" className="min-w-0 flex-1 text-left" aria-expanded={open === j.id} onClick={() => setOpen(open === j.id ? null : j.id)}>
                    <div className="font-medium">#{j.id} · {j.kind}{j.repository ? ` · ${j.repository}` : ''}{j.pull_request_number ? ` #${j.pull_request_number}` : ''}</div>
                    <div className="truncate text-xs text-muted">{j.finished_at ? `Finished ${formatDate(j.finished_at)}` : `Created ${formatDate(j.created_at)}`} · attempts {j.attempts}/{j.max_attempts}{j.error ? ` · ${j.error}` : ''}</div>
                  </button>
                  <StatusBadge status={j.status} />
                  {j.can_retry && <Button size="sm" variant="secondary" onClick={() => setConfirm(j)}><RotateCcw className="h-4 w-4" aria-hidden />Retry</Button>}
                  {!j.can_retry && j.status === 'processing' && <Badge tone="accent">Running</Badge>}
                </div>
                {open === j.id && <JobDetail id={j.id} />}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {list.data && <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onChange={setPage} />}
      <ConfirmDialog open={!!confirm} title={`Retry job #${confirm?.id}?`} confirmLabel="Retry job" loading={retry.isPending}
        description="The job returns to the queue with its attempt counter reset. Retrying is safe to repeat: a job that is no longer failed cannot be re-queued twice."
        onConfirm={() => retry.mutate(confirm.id)} onCancel={() => setConfirm(null)} />
    </div>
  )
}
