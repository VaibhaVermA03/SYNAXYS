import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { indexService } from '../../services'

// Polls the real index job; shows true counts (never a fake percentage when the total is not yet known).
export default function IndexProgress({ repositoryId }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['index-status', repositoryId], queryFn: () => indexService.status(repositoryId),
    refetchInterval: (query) => (['queued', 'indexing'].includes(query.state.data?.status) ? 3000 : false) })
  const status = q.data?.status
  useEffect(() => { if (status && !['queued', 'indexing'].includes(status)) qc.invalidateQueries({ queryKey: ['repositories'] }) }, [status, qc])
  if (!q.data) return null
  const job = q.data.job
  const known = job && job.files_total > 0
  return (
    <div className="mt-2 text-xs" role="status">
      {status === 'queued' && <span>Waiting for a worker to start indexing…</span>}
      {status === 'indexing' && (
        <div>
          <span>{known ? `Indexing: ${job.files_indexed} of ${job.files_total} files · ${job.chunks_upserted} chunks` : 'Indexing: reading repository…'}</span>
          <div className="mt-1 h-1.5 w-48 rounded-full bg-surface-2" role="progressbar" aria-label="Indexing progress" aria-valuemin={0} aria-valuemax={known ? job.files_total : undefined} aria-valuenow={known ? job.files_indexed : undefined}>
            <div className="h-1.5 rounded-full bg-accent transition-all" style={{ width: known ? `${Math.min(100, (job.files_indexed / job.files_total) * 100)}%` : '10%' }} />
          </div>
        </div>
      )}
      {status === 'failed' && <span className="text-danger">Indexing failed: {q.data.error || job?.error || 'unknown error'}</span>}
    </div>
  )
}
