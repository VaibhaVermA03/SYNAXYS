import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, FolderGit2, Lock, RefreshCw, Search } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Input, Pagination, Select, Skeleton } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { describeError } from '../../lib/api'
import { formatDate } from '../../lib/utils'
import { githubService, indexService } from '../../services'
import IndexProgress from '../../components/repositories/IndexProgress'

const PAGE_SIZE = 20
const INDEX_TONE = { not_indexed: 'neutral', queued: 'neutral', indexing: 'accent', indexed: 'ok', failed: 'danger' }

function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export default function RepositoriesPage() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [confirm, setConfirm] = useState(null)
  const q = useDebounced(search)
  useEffect(() => { setPage(1) }, [q, filter])

  const params = { q, page, page_size: PAGE_SIZE, connected: filter === 'all' ? undefined : filter === 'connected' }
  const repos = useQuery({ queryKey: ['repositories', params], queryFn: () => githubService.repositories(params), placeholderData: (p) => p, refetchInterval: (query) => (query.state.data?.items.some((i) => ['queued', 'indexing'].includes(i.index_status)) ? 5000 : false) })
  const installs = useQuery({ queryKey: ['installations'], queryFn: githubService.installations })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['repositories'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }) }

  const sync = useMutation({
    mutationFn: githubService.sync,
    onSuccess: (r) => { toast(`Synced ${r.repositories} repositories across ${r.installations} installation(s).${r.access_removed ? ` ${r.access_removed} no longer accessible.` : ''}`, 'success'); refresh(); qc.invalidateQueries({ queryKey: ['installations'] }) },
    onError: (e) => toast(e.code === 'github_reauth_required' ? 'GitHub credentials expired. Sign out and sign in with GitHub again, then sync.' : describeError(e), 'error'),
  })
  const connect = useMutation({
    mutationFn: githubService.connect,
    onSuccess: (r) => { toast(`Reviewing enabled for ${r.full_name}.`, 'success'); refresh() },
    onError: (e) => toast(describeError(e), 'error'),
  })
  const disconnect = useMutation({
    mutationFn: githubService.disconnect,
    onSuccess: (r) => { toast(`Reviewing disabled for ${r.full_name}. Indexed data will be deleted.`, 'success'); setConfirm(null); refresh() },
    onError: (e) => { toast(describeError(e), 'error'); setConfirm(null) },
  })

  const startIndex = useMutation({
    mutationFn: indexService.start,
    onSuccess: (r, id) => { toast('Indexing queued.', 'success'); refresh(); qc.invalidateQueries({ queryKey: ['index-status', id] }) },
    onError: (e) => toast(describeError(e), 'error'),
  })

  const installUrl = installs.data?.install_url
  const data = repos.data

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden />
          <Input className="pl-9" placeholder="Search repositories…" aria-label="Search repositories" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Select ariaLabel="Filter repositories" value={filter} onChange={setFilter} className="sm:w-44"
          options={[{ value: 'all', label: 'All' }, { value: 'connected', label: 'Connected' }, { value: 'disconnected', label: 'Not connected' }]} />
        {installUrl && <a href={installUrl} target="_blank" rel="noreferrer"><Button variant="secondary"><ExternalLink className="h-4 w-4" aria-hidden />Install GitHub App</Button></a>}
        <Button loading={sync.isPending} onClick={() => sync.mutate()}><RefreshCw className="h-4 w-4" aria-hidden />Sync from GitHub</Button>
      </div>

      <Card>
        {repos.isPending && <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}</div>}
        {repos.isError && <ErrorState message={describeError(repos.error)} onRetry={repos.refetch} />}
        {data && data.items.length === 0 && (
          <EmptyState icon={FolderGit2} title={q || filter !== 'all' ? 'No repositories match' : 'No repositories yet'}
            description={q || filter !== 'all' ? 'Try a different search or filter.' : 'Install the GitHub App on your account or organization, then press “Sync from GitHub”.'} />
        )}
        {data && data.items.length > 0 && (
          <ul className="divide-y divide-border">
            {data.items.map((r) => {
              const owner = r.role === 'owner'
              return (
                <li key={r.id} className="flex flex-wrap items-center gap-3 p-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{r.full_name}</span>
                      {r.is_private && <Lock className="h-3.5 w-3.5 text-muted" aria-label="Private repository" />}
                      {r.is_demo && <Badge tone="accent">Demo</Badge>}
                      {r.is_enabled && <Badge tone="ok">Reviewing</Badge>}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                      <span>Default branch: {r.default_branch}</span>{r.language && <span>{r.language}</span>}
                      <Badge tone={INDEX_TONE[r.index_status] || 'neutral'}>Index: {r.index_status.replace('_', ' ')}</Badge>
                      {r.last_indexed_at && <span>Last indexed {formatDate(r.last_indexed_at)}</span>}
                    </div>
                    {r.index_error && !['queued', 'indexing'].includes(r.index_status) && <p className="mt-1 text-xs text-danger">Indexing error: {r.index_error}</p>}
                    {['queued', 'indexing', 'failed'].includes(r.index_status) && <IndexProgress repositoryId={r.id} />}
                  </div>
                  {r.is_enabled && !r.is_demo && !['queued', 'indexing'].includes(r.index_status) && (
                    <Button variant="secondary" size="sm" disabled={!owner} title={owner ? undefined : 'Requires repository admin permission'} loading={startIndex.isPending && startIndex.variables === r.id}
                      onClick={() => startIndex.mutate(r.id)}>{r.index_status === 'indexed' ? 'Re-index' : r.index_status === 'failed' ? 'Retry indexing' : 'Index code'}</Button>
                  )}
                  {r.is_enabled ? (
                    <Button variant="secondary" size="sm" disabled={!owner} title={owner ? undefined : 'Requires repository admin permission'} onClick={() => setConfirm(r)}>Disconnect</Button>
                  ) : (
                    <Button size="sm" disabled={!owner} title={owner ? undefined : 'Requires repository admin permission'} loading={connect.isPending && connect.variables === r.id} onClick={() => connect.mutate(r.id)}>Connect</Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Card>
      {data && <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />}

      <ConfirmDialog open={!!confirm} danger title={`Disconnect ${confirm?.full_name}?`} confirmLabel="Disconnect" loading={disconnect.isPending}
        description="SYNAXYS will stop reviewing pull requests for this repository and delete its indexed code search data. Existing review history is kept."
        onCancel={() => setConfirm(null)} onConfirm={() => disconnect.mutate(confirm.id)} />
    </div>
  )
}
