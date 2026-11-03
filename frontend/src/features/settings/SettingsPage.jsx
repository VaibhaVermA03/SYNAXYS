import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, LogOut, Moon, Plug, Sun } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, ErrorState, Skeleton } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { useAuth } from '../../app/AuthProvider'
import { useTheme } from '../../app/ThemeProvider'
import { describeError } from '../../lib/api'
import { formatDate } from '../../lib/utils'
import { githubService, settingsService } from '../../services'

const LABELS = {
  'auth.login': 'Signed in', 'auth.logout': 'Signed out', 'auth.demo_login': 'Signed in (demo)', 'github.sync': 'Synced repositories from GitHub',
  'github.credentials_revoked': 'Revoked stored GitHub credentials', 'repository.connect': 'Enabled reviewing for a repository', 'repository.disconnect': 'Disabled reviewing for a repository',
  'repository.config_update': 'Changed repository review policy', 'repository.index_requested': 'Requested indexing', 'repository.indexed': 'Repository indexed',
  'review.requested': 'Requested a review', 'review.retry': 'Retried a review', 'review.approve': 'Approved review comments', 'review.publish': 'Published comments to GitHub',
  'comment.update': 'Edited or dismissed a comment', 'rule.create': 'Created a review rule', 'rule.update': 'Updated a review rule', 'rule.delete': 'Deleted a review rule',
}

export default function SettingsPage() {
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()
  const qc = useQueryClient()
  const { toast } = useToast()
  const [confirm, setConfirm] = useState(false)
  const integrations = useQuery({ queryKey: ['settings-integrations'], queryFn: settingsService.integrations })
  const audit = useQuery({ queryKey: ['settings-audit'], queryFn: () => settingsService.audit(50) })
  const revoke = useMutation({
    mutationFn: githubService.revokeCredentials,
    onSuccess: () => { toast('Stored GitHub credentials were deleted. Sign in with GitHub again to sync repositories.', 'success'); setConfirm(false); qc.invalidateQueries({ queryKey: ['settings-integrations'] }); qc.invalidateQueries({ queryKey: ['settings-audit'] }) },
    onError: (e) => { toast(describeError(e), 'error'); setConfirm(false) },
  })
  const stored = integrations.data?.github_token_stored

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-3 p-4">
        {user?.avatar_url && <img src={user.avatar_url} alt="" className="h-12 w-12 rounded-full" />}
        <div className="min-w-0 flex-1"><h2 className="font-semibold">{user?.name || user?.login}</h2><p className="text-sm text-muted">@{user?.login} · signed in with GitHub</p></div>
        <Button variant="secondary" onClick={logout}><LogOut className="h-4 w-4" aria-hidden />Sign out</Button>
      </Card>

      <Card className="flex flex-wrap items-center gap-3 p-4">
        <div className="flex-1"><h2 className="font-semibold">Appearance</h2><p className="text-sm text-muted">Current theme: {theme}</p></div>
        <Button variant="secondary" onClick={toggle}>{theme === 'dark' ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}Switch to {theme === 'dark' ? 'light' : 'dark'}</Button>
      </Card>

      <Card className="space-y-2 p-4">
        <h2 className="flex items-center gap-2 font-semibold"><Plug className="h-4 w-4" aria-hidden />Integrations and review policy</h2>
        <p className="text-sm text-muted">See which services are configured, and choose per repository how review comments are published.</p>
        <Link to="/app/settings/integrations"><Button variant="secondary">Open integration settings</Button></Link>
      </Card>

      <Card className="space-y-2 p-4">
        <h2 className="flex items-center gap-2 font-semibold"><KeyRound className="h-4 w-4" aria-hidden />GitHub credentials</h2>
        <p className="text-sm text-muted">SYNAXYS stores your GitHub access token encrypted so it can list the repositories you can access. It is never shown or sent to your browser.</p>
        {integrations.isPending ? <Skeleton className="h-9 w-48" /> : stored ? (
          <Button variant="danger" onClick={() => setConfirm(true)}>Revoke stored GitHub credentials</Button>
        ) : <p className="text-sm"><Badge>No token stored</Badge> <span className="text-muted">Sign in with GitHub again to sync repositories.</span></p>}
      </Card>

      <Card className="p-4">
        <h2 className="mb-2 font-semibold">Your recent activity</h2>
        {audit.isPending && <Skeleton className="h-24" />}
        {audit.isError && <ErrorState message={describeError(audit.error)} onRetry={audit.refetch} />}
        {audit.data?.length === 0 && <p className="text-sm text-muted">No activity recorded yet.</p>}
        {audit.data?.length > 0 && (
          <ul className="divide-y divide-border text-sm">
            {audit.data.map((a) => <li key={a.id} className="flex flex-wrap justify-between gap-2 py-1.5"><span>{LABELS[a.action] || a.action}{a.target_id ? <span className="text-muted"> · {a.target_type} #{a.target_id}</span> : null}</span><span className="text-xs text-muted">{formatDate(a.created_at)}</span></li>)}
          </ul>
        )}
      </Card>

      <ConfirmDialog open={confirm} danger title="Revoke stored GitHub credentials?" confirmLabel="Revoke" loading={revoke.isPending}
        description="The encrypted token will be deleted. You stay signed in, but syncing repositories needs a new GitHub sign-in. This does not uninstall the GitHub App."
        onCancel={() => setConfirm(false)} onConfirm={() => revoke.mutate()} />
    </div>
  )
}
