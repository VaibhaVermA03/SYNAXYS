import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCheck } from 'lucide-react'
import { Badge, Button, Card, EmptyState, ErrorState, Pagination, Skeleton } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { describeError } from '../../lib/api'
import { formatDate } from '../../lib/utils'
import { notificationService } from '../../services'

export default function NotificationsPage() {
  const [page, setPage] = useState(1)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const qc = useQueryClient()
  const { toast } = useToast()
  const q = useQuery({ queryKey: ['notifications', { page, unreadOnly }], queryFn: () => notificationService.list({ page, page_size: 20, unread: unreadOnly || undefined }), placeholderData: (p) => p })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['notifications'] }); qc.invalidateQueries({ queryKey: ['notifications-unread'] }) }
  const read = useMutation({ mutationFn: notificationService.read, onSuccess: refresh, onError: (e) => toast(describeError(e), 'error') })
  const readAll = useMutation({ mutationFn: notificationService.readAll, onSuccess: refresh, onError: (e) => toast(describeError(e), 'error') })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={unreadOnly ? 'primary' : 'secondary'} aria-pressed={unreadOnly} onClick={() => { setUnreadOnly((v) => !v); setPage(1) }}>Unread only</Button>
        <Button size="sm" variant="secondary" loading={readAll.isPending} disabled={!q.data?.unread} onClick={() => readAll.mutate()}><CheckCheck className="h-4 w-4" aria-hidden />Mark all as read{q.data?.unread ? ` (${q.data.unread})` : ''}</Button>
      </div>
      <Card>
        {q.isPending && <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}</div>}
        {q.isError && <ErrorState message={describeError(q.error)} onRetry={q.refetch} />}
        {q.data?.items.length === 0 && <EmptyState icon={Bell} title={unreadOnly ? 'No unread notifications' : 'No notifications yet'} description="Reviews, indexing and workspace activity will show up here." />}
        {q.data?.items.length > 0 && (
          <ul className="divide-y divide-border">
            {q.data.items.map((n) => (
              <li key={n.id} className={`flex flex-wrap items-start gap-3 p-4 text-sm ${n.read ? 'opacity-70' : ''}`}>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {!n.read && <span className="h-2 w-2 rounded-full bg-accent" aria-label="Unread" />}
                    {n.link ? <Link to={n.link} onClick={() => !n.read && read.mutate(n.id)} className="font-medium hover:underline">{n.title}</Link> : <span className="font-medium">{n.title}</span>}
                    <Badge>{n.kind.replace(/_/g, ' ')}</Badge>
                  </div>
                  {n.body && <p className="mt-0.5 text-xs text-muted">{n.body}</p>}
                  <p className="mt-0.5 text-xs text-muted">{formatDate(n.created_at)}</p>
                </div>
                {!n.read && <Button size="sm" variant="ghost" onClick={() => read.mutate(n.id)}>Mark as read</Button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {q.data && <Pagination page={q.data.page} pageSize={q.data.page_size} total={q.data.total} onChange={setPage} />}
    </div>
  )
}
