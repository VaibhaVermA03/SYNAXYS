import { useCallback, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { EyeOff, RotateCcw } from 'lucide-react'
import { Button, ConfirmDialog } from '../ui'
import { useToast } from '../ui/Toast'
import { ApiError, describeError } from '../../lib/api'
import { reviewService } from '../../services'

const REASONS = [['', 'No reason'], ['false_positive', 'False positive'], ['not_applicable', 'Not applicable'], ['will_fix_later', 'Will fix later'], ['accepted_risk', 'Accepted risk'], ['other', 'Other']]

// Finding-level dismissal. Independent of any GitHub comment: it needs no comment, deletes nothing, and records who/when/why.
// (A comment's own "Cancel comment" / "Delete from GitHub" controls live in CommentActions and do not change the finding.)
export default function FindingActions({ reviewId, finding, canManage }) {
  const qc = useQueryClient()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [fieldError, setFieldError] = useState(null)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['review', String(reviewId)] }); qc.invalidateQueries({ queryKey: ['review', reviewId] }); qc.invalidateQueries({ queryKey: ['reviews'] }) }
  const dismiss = useMutation({
    mutationFn: () => reviewService.dismissFinding(reviewId, finding.id, { reason: reason || null, note: note.trim() || null }),
    onSuccess: () => { setOpen(false); setReason(''); setNote(''); setFieldError(null); toast('Finding dismissed.', 'success'); refresh() },
    onError: (e) => { if (e instanceof ApiError && e.fields?.length) setFieldError(e.fields[0].msg); else toast(describeError(e), 'error') },
  })
  const restore = useMutation({ mutationFn: () => reviewService.restoreFinding(reviewId, finding.id), onSuccess: () => { toast('Finding restored.', 'success'); refresh() }, onError: (e) => toast(describeError(e), 'error') })
  const close = useCallback(() => { setOpen(false); setFieldError(null) }, []) // stable: ConfirmDialog refocuses its Cancel button whenever onCancel changes
  if (!canManage) return null
  const dismissed = finding.status === 'dismissed'
  return (
    <div className="ml-3 mt-1 flex flex-wrap items-center gap-2 text-sm">
      {dismissed
        ? <Button size="sm" variant="secondary" loading={restore.isPending} onClick={() => restore.mutate()}><RotateCcw className="h-3.5 w-3.5" aria-hidden />Restore finding</Button>
        : <Button size="sm" variant="ghost" onClick={() => setOpen(true)}><EyeOff className="h-3.5 w-3.5" aria-hidden />Dismiss finding</Button>}
      <ConfirmDialog open={open} title="Dismiss this finding?" confirmLabel="Dismiss" loading={dismiss.isPending}
        description="The finding is kept (with who dismissed it and when) but hidden from the active list and counts, and will not be proposed again on this pull request. Any pending comment for it is cancelled. A comment already on GitHub is not touched."
        onCancel={close} onConfirm={() => dismiss.mutate()}>
        <div className="space-y-2 text-sm">
          <label className="block text-xs font-medium text-muted" htmlFor={`reason-${finding.id}`}>Reason (optional)</label>
          <select id={`reason-${finding.id}`} value={reason} onChange={(e) => setReason(e.target.value)} className="w-full rounded-lg border border-border bg-surface px-3 py-2">
            {REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <label className="block text-xs font-medium text-muted" htmlFor={`note-${finding.id}`}>Note (optional)</label>
          <textarea id={`note-${finding.id}`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} rows={2} className="w-full rounded-lg border border-border bg-surface px-3 py-2" />
          {fieldError && <p role="alert" className="text-xs text-danger">{fieldError}</p>}
        </div>
      </ConfirmDialog>
    </div>
  )
}
