import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GitBranch, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Select, Skeleton } from '../ui'
import { useToast } from '../ui/Toast'
import { describeError } from '../../lib/api'
import { indexService } from '../../services'

const TONE = { indexed: 'ok', partial: 'warn', failed: 'danger', missing: 'danger', indexing: 'accent', queued: 'accent' }

// Per-branch indexing controls (repository admins). Collapsed by default: nothing is fetched until it is opened.
export default function BranchIndexPanel({ repository }) {
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [pick, setPick] = useState('')
  const [remove, setRemove] = useState(null)
  const qc = useQueryClient()
  const { toast } = useToast()
  const key = ['index-status', repository.id, 'panel']
  const status = useQuery({ queryKey: key, queryFn: () => indexService.status(repository.id), enabled: open,
    refetchInterval: (q) => ((q.state.data?.branches || []).some((b) => ['queued', 'indexing'].includes(b.status)) ? 3000 : false) })
  const gh = useQuery({ queryKey: ['github-branches', repository.id], queryFn: () => indexService.githubBranches(repository.id), enabled: open && adding, retry: false })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['index-status', repository.id] }); qc.invalidateQueries({ queryKey: ['repositories'] }); qc.invalidateQueries({ queryKey: ['search-branches'] }) }
  const onError = (e) => toast(describeError(e), 'error')
  const start = useMutation({ mutationFn: (b) => indexService.start(repository.id, b), onSuccess: () => { toast('Indexing queued.', 'success'); setAdding(false); setPick(''); refresh() }, onError })
  const retry = useMutation({ mutationFn: (b) => indexService.retryFailed(repository.id, b), onSuccess: () => { toast('Continuing: only the missing work will run.', 'success'); refresh() }, onError })
  const del = useMutation({ mutationFn: (b) => indexService.removeBranch(repository.id, b), onSuccess: () => { toast('Branch index removal queued.', 'success'); refresh() }, onError, onSettled: () => setRemove(null) })
  const branches = status.data?.branches || []
  const candidates = (gh.data?.branches || []).filter((b) => !branches.some((x) => x.branch === b))
  return (
    <div className="mt-2 text-xs">
      <button type="button" className="inline-flex items-center gap-1 text-accent-ink hover:underline" aria-expanded={open} onClick={() => setOpen((v) => !v)}><GitBranch className="h-3 w-3" aria-hidden />Branches</button>
      {open && (
        <div className="mt-2 space-y-2 rounded-lg border border-border p-3">
          {status.isPending && <Skeleton className="h-10" />}
          {status.isError && <p className="text-danger">{describeError(status.error)}</p>}
          {status.isSuccess && branches.length === 0 && <p className="text-muted">No branch is indexed yet. Use “Index code” for the default branch or add another branch below.</p>}
          <ul className="space-y-2">
            {branches.map((b) => (
              <li key={b.branch} className="flex flex-wrap items-center gap-2">
                <span className="font-mono font-medium">{b.branch}</span>{b.is_default && <Badge>default</Badge>}<Badge tone={TONE[b.status] || 'neutral'}>{b.status}</Badge>
                <span className="text-muted">{b.files_indexed} files{b.files_deferred ? ` · ${b.files_deferred} eligible files left out by the file limit` : ''}{b.tree_incomplete ? ' · repository listing incomplete (nothing was deleted)' : ''}</span>
                {b.error && !['indexed'].includes(b.status) && <span className={b.status === 'partial' ? 'text-warn' : 'text-danger'}>{b.error}</span>}
                <span className="ml-auto flex gap-1">
                  {b.status === 'partial' && <Button size="sm" variant="secondary" loading={retry.isPending && retry.variables === b.branch} onClick={() => retry.mutate(b.branch)}><RotateCcw className="h-3 w-3" aria-hidden />Continue</Button>}
                  {!['queued', 'indexing'].includes(b.status) && !b.is_default && b.status !== 'partial' && <Button size="sm" variant="ghost" loading={start.isPending && start.variables === b.branch} onClick={() => start.mutate(b.branch)}>Re-index</Button>}
                  {!['queued', 'indexing'].includes(b.status) && !b.is_default && <Button size="sm" variant="ghost" aria-label={`Remove index of ${b.branch}`} onClick={() => setRemove(b)}><Trash2 className="h-3 w-3" aria-hidden /></Button>}
                </span>
              </li>
            ))}
          </ul>
          {!adding
            ? <Button size="sm" variant="secondary" onClick={() => setAdding(true)}><Plus className="h-3 w-3" aria-hidden />Index another branch</Button>
            : (
              <div className="flex flex-wrap items-center gap-2">
                {gh.isPending && <Skeleton className="h-8 w-48" />}
                {gh.isError && <span className="text-danger">{describeError(gh.error)}</span>}
                {gh.isSuccess && <Select ariaLabel="Branch to index" className="w-56" value={pick} onChange={setPick} options={[{ value: '', label: candidates.length ? 'Choose a branch…' : 'No other branches' }, ...candidates.map((b) => ({ value: b, label: b }))]} />}
                <Button size="sm" disabled={!pick} loading={start.isPending && start.variables === pick} onClick={() => start.mutate(pick)}>Index branch</Button>
                <Button size="sm" variant="ghost" onClick={() => { setAdding(false); setPick('') }}>Cancel</Button>
                {gh.isSuccess && <span className="text-muted">Up to {gh.data.max_extra_branches} extra branches per repository.</span>}
              </div>
            )}
        </div>
      )}
      <ConfirmDialog open={!!remove} danger title={`Remove the index of “${remove?.branch}”?`} confirmLabel="Remove index" loading={del.isPending}
        description="Search results for this branch disappear. The branch itself on GitHub and the other indexed branches are not touched. You can index it again later."
        onCancel={() => setRemove(null)} onConfirm={() => del.mutate(remove.branch)} />
    </div>
  )
}
