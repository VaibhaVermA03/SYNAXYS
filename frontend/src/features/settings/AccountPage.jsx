import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Trash2 } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, Skeleton } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { useAuth } from '../../app/AuthProvider'
import { ApiError, describeError } from '../../lib/api'
import { formatDate } from '../../lib/utils'
import { accountService } from '../../services'

const input = 'w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm'

export default function AccountPage() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [needLogin, setNeedLogin] = useState(false)
  const exports = useQuery({ queryKey: ['account-exports'], queryFn: accountService.exports, refetchInterval: (q) => ((q.state.data || []).some((e) => e.status === 'pending') ? 3000 : false) })
  const request = useMutation({ mutationFn: accountService.requestExport, onSuccess: () => { toast('Preparing your export…', 'success'); qc.invalidateQueries({ queryKey: ['account-exports'] }) }, onError: (e) => toast(describeError(e), 'error') })
  const del = useMutation({
    mutationFn: () => accountService.remove(typed),
    onSuccess: () => { window.location.assign('/login') },  // the session is gone; start from the login page
    onError: (e) => { if (e instanceof ApiError && e.status === 403 && !e.code?.includes('csrf')) setNeedLogin(true); else toast(describeError(e), 'error'); setOpen(false) },
  })
  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <h3 className="text-sm font-medium">Export your data</h3>
        <p className="text-xs text-muted">A ZIP with your profile, workspace memberships, review rules, activity, notifications and the review history, findings and comments you can access. It never contains credentials or other people’s private data, and it expires after 24 hours.</p>
        <Button loading={request.isPending} onClick={() => request.mutate()}><Download className="h-4 w-4" aria-hidden />Request export</Button>
        {exports.isPending && <Skeleton className="h-10" />}
        <ul className="divide-y divide-border text-sm">
          {(exports.data || []).map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-2 py-2">
              <span>Export #{e.id}</span><Badge tone={e.status === 'ready' ? 'ok' : e.status === 'failed' ? 'danger' : 'accent'}>{e.status}</Badge>
              <span className="text-xs text-muted">{formatDate(e.created_at)} · expires {formatDate(e.expires_at)}{e.size_bytes ? ` · ${(e.size_bytes / 1024).toFixed(0)} KB` : ''}</span>
              {e.status === 'ready' && <a className="ml-auto text-xs text-accent-ink hover:underline" href={accountService.downloadUrl(e.id)} download>Download</a>}
            </li>
          ))}
        </ul>
      </Card>
      <Card className="space-y-3 border-danger/40 p-4">
        <h3 className="text-sm font-medium text-danger">Delete your account</h3>
        <p className="text-xs text-muted">Removes your profile, sessions, stored GitHub token (and revokes it at GitHub when possible), notifications and exports. Workspaces you share with others stay (ownership passes to another member); workspaces where you are the only member are deleted together with all review data and the search index of their repositories. This cannot be undone.</p>
        {needLogin && <p role="alert" className="text-xs text-danger">For your security please sign in with GitHub again, then delete your account within 15 minutes. <a className="underline" href="/login">Sign in again</a></p>}
        <Button variant="secondary" onClick={() => setOpen(true)}><Trash2 className="h-4 w-4" aria-hidden />Delete my account</Button>
      </Card>
      <ConfirmDialog open={open} danger title="Delete your account permanently?" confirmLabel="Delete account" loading={del.isPending}
        description={`Type your GitHub username (${user?.login}) to confirm.`} onCancel={() => { setOpen(false); setTyped('') }} onConfirm={() => typed.trim().toLowerCase() === (user?.login || '').toLowerCase() && del.mutate()}>
        <input aria-label="Type your GitHub username" className={input} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
      </ConfirmDialog>
    </div>
  )
}
