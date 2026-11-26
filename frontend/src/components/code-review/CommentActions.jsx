import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Pencil, RotateCcw, Trash2, X } from 'lucide-react'
import { Badge, Button, ConfirmDialog } from '../ui'
import { useToast } from '../ui/Toast'
import { ApiError, describeError } from '../../lib/api'
import { reviewService } from '../../services'

const TONE = { draft: 'neutral', approved: 'accent', publishing: 'warn', published: 'ok', failed: 'danger', cancelled: 'neutral', deleted: 'neutral' }

// The proposed GitHub comment for one finding, with explicit human controls. Nothing is posted from here:
// approving only marks it eligible; posting happens through the review-level "Publish" confirmation.
export default function CommentActions({ reviewId, comment, canManage }) {
  const qc = useQueryClient()
  const { toast } = useToast()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(comment.body)
  const [fieldError, setFieldError] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['review', String(reviewId)] }); qc.invalidateQueries({ queryKey: ['review', reviewId] }) }

  const patch = useMutation({
    mutationFn: (body) => reviewService.updateComment(reviewId, comment.id, body),
    onSuccess: () => { setEditing(false); setFieldError(null); refresh() },
    onError: (e) => { if (e instanceof ApiError && e.fields?.length) setFieldError(e.fields[0].msg); else toast(describeError(e), 'error') },
  })
  const approve = useMutation({ mutationFn: () => reviewService.approve(reviewId, [comment.id]), onSuccess: refresh, onError: (e) => toast(describeError(e), 'error') })
  const remove = useMutation({
    mutationFn: () => reviewService.deleteGithubComment(reviewId, comment.id),
    onSuccess: (r) => { setConfirmDelete(false); toast(r.outcome === 'already_deleted' ? 'The comment was already gone from GitHub; SYNAXYS now shows it as deleted.' : 'Comment deleted from GitHub.', 'success'); qc.invalidateQueries({ queryKey: ['review-attempts'] }); refresh() },
    onError: (e) => { setConfirmDelete(false); toast(describeError(e), 'error'); refresh() },
  })
  const locked = ['published', 'publishing', 'deleted'].includes(comment.state)

  return (
    <div className="ml-3 mt-1 rounded-lg border border-dashed border-border bg-surface-2/50 p-3 text-sm" aria-label="Proposed GitHub comment">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">Proposed GitHub comment <Badge tone={TONE[comment.state]}>{comment.state}</Badge>{comment.edited && <Badge>edited</Badge>}</div>
      {editing ? (
        <div className="space-y-2">
          <textarea aria-label="Comment text" value={text} onChange={(e) => setText(e.target.value)} rows={6} className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs" />
          {fieldError && <p role="alert" className="text-xs text-danger">{fieldError}</p>}
          <div className="flex gap-2">
            <Button size="sm" loading={patch.isPending} onClick={() => patch.mutate({ body: text })}>Save</Button>
            <Button size="sm" variant="secondary" onClick={() => { setEditing(false); setText(comment.body); setFieldError(null) }}>Cancel</Button>
          </div>
          <p className="text-xs text-muted">Saving an edit moves the comment back to draft; it must be approved again.</p>
        </div>
      ) : <pre className="max-h-48 overflow-auto whitespace-pre-wrap font-sans text-xs">{comment.body}</pre>}
      {canManage && !locked && !editing && (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => setEditing(true)}><Pencil className="h-3.5 w-3.5" aria-hidden />Edit</Button>
          {comment.state === 'draft' && <Button size="sm" loading={approve.isPending} onClick={() => approve.mutate()}><Check className="h-3.5 w-3.5" aria-hidden />Approve</Button>}
          {comment.state === 'approved' && <Button size="sm" variant="secondary" loading={patch.isPending} onClick={() => patch.mutate({ state: 'draft' })}><RotateCcw className="h-3.5 w-3.5" aria-hidden />Unapprove</Button>}
          {comment.state === 'failed' && <Button size="sm" variant="secondary" onClick={() => patch.mutate({ state: 'draft' })}><RotateCcw className="h-3.5 w-3.5" aria-hidden />Back to draft</Button>}
          {comment.state === 'cancelled' && <Button size="sm" variant="secondary" onClick={() => patch.mutate({ state: 'draft' })}><RotateCcw className="h-3.5 w-3.5" aria-hidden />Restore</Button>}
          {comment.state !== 'cancelled' && <Button size="sm" variant="ghost" title="Do not publish this comment. The finding itself stays active; use “Dismiss finding” to dismiss the finding." onClick={() => patch.mutate({ state: 'cancelled' })}><X className="h-3.5 w-3.5" aria-hidden />Cancel comment</Button>}
        </div>
      )}
      {canManage && comment.state === 'published' && (
        <div className="mt-2"><Button size="sm" variant="ghost" onClick={() => setConfirmDelete(true)}><Trash2 className="h-3.5 w-3.5" aria-hidden />Delete from GitHub</Button></div>
      )}
      {comment.state === 'deleted' && <p className="mt-1 text-xs text-muted">Deleted from GitHub{comment.github_deleted_at ? ` on ${new Date(comment.github_deleted_at).toLocaleDateString()}` : ''}. The record is kept here.</p>}
      {comment.state === 'failed' && <p className="mt-1 text-xs text-danger">GitHub rejected this comment’s location. It was not posted.</p>}
      <ConfirmDialog open={confirmDelete} danger title="Delete this comment from GitHub?" confirmLabel="Delete from GitHub" loading={remove.isPending}
        description="SYNAXYS first checks on GitHub that this comment belongs to this pull request and was created by SYNAXYS, then deletes it and confirms it is gone. Deleting on GitHub cannot be undone. The finding and this record stay in SYNAXYS."
        onCancel={() => setConfirmDelete(false)} onConfirm={() => remove.mutate()} />
    </div>
  )
}
