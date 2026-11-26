import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, LogOut, Plus, Trash2, UserPlus } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Select, Skeleton } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { useAuth } from '../../app/AuthProvider'
import { useWorkspace } from '../../app/WorkspaceProvider'
import { describeError } from '../../lib/api'
import { formatDate } from '../../lib/utils'
import { workspaceService } from '../../services'

const ROLE_TONE = { owner: 'accent', admin: 'ok', member: 'neutral' }
const input = 'w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm'
const rank = { member: 1, admin: 2, owner: 3 }

function useAction(fn, { ok, after }) {
  const { toast } = useToast()
  return useMutation({ mutationFn: fn, onSuccess: (r) => { if (ok) toast(ok, 'success'); after?.(r) }, onError: (e) => toast(describeError(e), 'error') })
}

function CreateAndInvitations() {
  const qc = useQueryClient()
  const { setActive } = useWorkspace()
  const [name, setName] = useState('')
  const mine = useQuery({ queryKey: ['my-invitations'], queryFn: workspaceService.myInvitations, retry: false })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['workspaces'] }); qc.invalidateQueries({ queryKey: ['my-invitations'] }) }
  const create = useAction(() => workspaceService.create(name.trim()), { ok: 'Workspace created.', after: (ws) => { setName(''); refresh(); setActive(ws.id) } })
  const decline = useAction((id) => workspaceService.decline(id), { ok: 'Invitation declined.', after: refresh })
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card className="space-y-3 p-4">
        <h3 className="text-sm font-medium">Create a workspace</h3>
        <div className="flex gap-2">
          <input aria-label="Workspace name" className={input} value={name} maxLength={100} onChange={(e) => setName(e.target.value)} placeholder="e.g. Platform team" />
          <Button disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate()}><Plus className="h-4 w-4" aria-hidden />Create</Button>
        </div>
        <p className="text-xs text-muted">A workspace owns repositories, reviews and findings. You become its owner.</p>
      </Card>
      <Card className="space-y-2 p-4">
        <h3 className="text-sm font-medium">Invitations for you</h3>
        {(mine.data || []).length === 0 && <p className="text-xs text-muted">No pending invitations.</p>}
        {(mine.data || []).map((i) => (
          <div key={i.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{i.workspace_name}</span><Badge tone={ROLE_TONE[i.role]}>{i.role}</Badge><span className="text-xs text-muted">expires {formatDate(i.expires_at)}</span>
            <span className="ml-auto flex gap-1"><Button size="sm" variant="ghost" onClick={() => decline.mutate(i.id)}>Decline</Button></span>
          </div>
        ))}
        {(mine.data || []).length > 0 && <p className="text-xs text-muted">To accept, open the invitation link you were sent (/app/invitations/…).</p>}
      </Card>
    </div>
  )
}

function General({ ws }) {
  const qc = useQueryClient()
  const [name, setName] = useState(ws.name)
  const refresh = () => qc.invalidateQueries({ queryKey: ['workspaces'] })
  const save = useAction((body) => workspaceService.update(ws.id, body), { ok: 'Saved.', after: refresh })
  const canEdit = rank[ws.role] >= 2
  return (
    <Card className="space-y-3 p-4">
      <h3 className="text-sm font-medium">General</h3>
      <div className="flex gap-2">
        <input aria-label="Name" className={input} value={name} maxLength={100} disabled={!canEdit} onChange={(e) => setName(e.target.value)} />
        {canEdit && <Button disabled={!name.trim() || name.trim() === ws.name} loading={save.isPending} onClick={() => save.mutate({ name: name.trim() })}>Save</Button>}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">Who can invite:</span>
        {ws.role === 'owner'
          ? <Select ariaLabel="Who can invite" className="w-48" value={ws.invite_policy} onChange={(v) => save.mutate({ invite_policy: v })} options={[{ value: 'admin', label: 'Owner and admins' }, { value: 'owner', label: 'Owner only' }]} />
          : <Badge>{ws.invite_policy === 'owner' ? 'Owner only' : 'Owner and admins'}</Badge>}
      </div>
    </Card>
  )
}

function Members({ ws, me }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['workspace-members', ws.id], queryFn: () => workspaceService.members(ws.id) })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['workspace-members', ws.id] }); qc.invalidateQueries({ queryKey: ['workspaces'] }) }
  const setRole = useAction(({ id, role }) => workspaceService.setRole(ws.id, id, role), { ok: 'Role updated.', after: refresh })
  const remove = useAction((id) => workspaceService.removeMember(ws.id, id), { ok: 'Member removed.', after: refresh })
  const transfer = useAction((id) => workspaceService.transfer(ws.id, id), { ok: 'Ownership transferred.', after: () => { refresh(); qc.invalidateQueries({ queryKey: ['audit'] }) } })
  const [confirm, setConfirm] = useState(null) // { kind, member }
  const canRemove = (m) => m.login !== me && m.role !== 'owner' && (ws.role === 'owner' || (ws.role === 'admin' && m.role === 'member'))
  return (
    <Card className="space-y-3 p-4">
      <h3 className="text-sm font-medium">Members{q.data ? ` (${q.data.length})` : ''}</h3>
      {q.isPending && <Skeleton className="h-16" />}
      {q.isError && <ErrorState message={describeError(q.error)} onRetry={q.refetch} />}
      <ul className="divide-y divide-border">
        {(q.data || []).map((m) => (
          <li key={m.user_id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
            {m.avatar_url && <img src={m.avatar_url} alt="" className="h-6 w-6 rounded-full" />}
            <span className="font-medium">{m.login}{m.login === me ? ' (you)' : ''}</span>
            {ws.role === 'owner' && m.role !== 'owner' && m.login !== me
              ? <Select ariaLabel={`Role of ${m.login}`} className="w-32" value={m.role} onChange={(role) => setRole.mutate({ id: m.user_id, role })} options={[{ value: 'admin', label: 'Admin' }, { value: 'member', label: 'Member' }]} />
              : <Badge tone={ROLE_TONE[m.role]}>{m.role}</Badge>}
            <span className="text-xs text-muted">joined {formatDate(m.joined_at)}</span>
            <span className="ml-auto flex gap-1">
              {ws.role === 'owner' && m.role !== 'owner' && <Button size="sm" variant="ghost" onClick={() => setConfirm({ kind: 'transfer', member: m })}>Make owner</Button>}
              {canRemove(m) && <Button size="sm" variant="ghost" aria-label={`Remove ${m.login}`} onClick={() => setConfirm({ kind: 'remove', member: m })}><Trash2 className="h-3.5 w-3.5" aria-hidden /></Button>}
            </span>
          </li>
        ))}
      </ul>
      <ConfirmDialog open={!!confirm} danger title={confirm?.kind === 'transfer' ? `Make ${confirm?.member.login} the owner?` : `Remove ${confirm?.member.login}?`} confirmLabel={confirm?.kind === 'transfer' ? 'Transfer ownership' : 'Remove'}
        description={confirm?.kind === 'transfer' ? 'They become the owner and you become an admin. Only the new owner can undo this.' : 'They lose access to all repositories, reviews and findings of this workspace immediately.'}
        onCancel={() => setConfirm(null)} onConfirm={() => { (confirm.kind === 'transfer' ? transfer : remove).mutate(confirm.member.user_id); setConfirm(null) }} />
    </Card>
  )
}

function Invitations({ ws }) {
  const qc = useQueryClient()
  const [login, setLogin] = useState('')
  const [role, setRole] = useState('member')
  const [link, setLink] = useState(null)
  const q = useQuery({ queryKey: ['workspace-invitations', ws.id], queryFn: () => workspaceService.invitations(ws.id) })
  const refresh = () => qc.invalidateQueries({ queryKey: ['workspace-invitations', ws.id] })
  const invite = useAction(() => workspaceService.invite(ws.id, login.trim(), role), { after: (r) => { setLink(`${window.location.origin}/app/invitations/${r.token}`); setLogin(''); refresh() } })
  const revoke = useAction((id) => workspaceService.revokeInvitation(ws.id, id), { ok: 'Invitation revoked.', after: refresh })
  const { toast } = useToast()
  const canInvite = ws.invite_policy === 'owner' ? ws.role === 'owner' : rank[ws.role] >= 2
  return (
    <Card className="space-y-3 p-4">
      <h3 className="text-sm font-medium">Invitations</h3>
      {canInvite && (
        <div className="flex flex-wrap gap-2">
          <input aria-label="GitHub username" className={`${input} sm:w-56`} value={login} onChange={(e) => setLogin(e.target.value)} placeholder="GitHub username" />
          <Select ariaLabel="Invitation role" className="w-32" value={role} onChange={setRole} options={ws.role === 'owner' ? [{ value: 'member', label: 'Member' }, { value: 'admin', label: 'Admin' }] : [{ value: 'member', label: 'Member' }]} />
          <Button disabled={!login.trim()} loading={invite.isPending} onClick={() => invite.mutate()}><UserPlus className="h-4 w-4" aria-hidden />Invite</Button>
        </div>
      )}
      {link && (
        <div role="status" className="space-y-1 rounded-lg border border-border p-3 text-xs">
          <p className="font-medium">Invitation link (shown only once, valid for 7 days). Send it to exactly this GitHub user:</p>
          <div className="flex items-center gap-2"><code className="min-w-0 flex-1 break-all">{link}</code>
            <Button size="sm" variant="secondary" onClick={() => { navigator.clipboard?.writeText(link); toast('Link copied.', 'success') }}><Copy className="h-3.5 w-3.5" aria-hidden />Copy</Button></div>
        </div>
      )}
      <ul className="divide-y divide-border">
        {(q.data || []).map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
            <span className="font-medium">{i.login}</span><Badge tone={ROLE_TONE[i.role]}>{i.role}</Badge><Badge tone={i.status === 'pending' ? 'accent' : 'neutral'}>{i.status}</Badge>
            <span className="text-xs text-muted">{i.status === 'pending' ? `expires ${formatDate(i.expires_at)}` : formatDate(i.created_at)}</span>
            {i.status === 'pending' && canInvite && <Button size="sm" variant="ghost" className="ml-auto" onClick={() => revoke.mutate(i.id)}>Revoke</Button>}
          </li>
        ))}
        {q.data?.length === 0 && <li className="py-2 text-xs text-muted">No invitations yet.</li>}
      </ul>
    </Card>
  )
}

function Activity({ ws }) {
  const q = useQuery({ queryKey: ['audit', ws.id], queryFn: () => workspaceService.audit(ws.id) })
  return (
    <Card className="space-y-2 p-4">
      <h3 className="text-sm font-medium">Workspace activity</h3>
      {q.isPending && <Skeleton className="h-12" />}
      {q.data?.length === 0 && <p className="text-xs text-muted">No activity yet.</p>}
      <ul className="max-h-72 divide-y divide-border overflow-y-auto text-xs">
        {(q.data || []).map((e) => <li key={e.id} className="flex flex-wrap gap-2 py-1.5"><span className="font-medium">{e.action}</span><span className="text-muted">{e.actor || 'system'} · {formatDate(e.created_at)}</span></li>)}
      </ul>
    </Card>
  )
}

function Danger({ ws }) {
  const qc = useQueryClient()
  const [leave, setLeave] = useState(false)
  const [del, setDel] = useState(false)
  const [typed, setTyped] = useState('')
  const done = () => { qc.invalidateQueries({ queryKey: ['workspaces'] }); qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== 'me' }) }
  const leaveM = useAction(() => workspaceService.leave(ws.id), { ok: 'You left the workspace.', after: () => { setLeave(false); done() } })
  const delM = useAction(() => workspaceService.remove(ws.id, typed), { ok: 'Workspace deleted.', after: () => { setDel(false); setTyped(''); done() } })
  return (
    <Card className="space-y-3 border-danger/40 p-4">
      <h3 className="text-sm font-medium text-danger">Danger zone</h3>
      {ws.role !== 'owner' && <Button variant="secondary" onClick={() => setLeave(true)}><LogOut className="h-4 w-4" aria-hidden />Leave workspace</Button>}
      {ws.role === 'owner' && <>
        <p className="text-xs text-muted">The owner cannot leave: transfer ownership first, or delete the workspace. Deleting disconnects its repositories and removes their search index.</p>
        <Button variant="secondary" onClick={() => setDel(true)}><Trash2 className="h-4 w-4" aria-hidden />Delete workspace</Button>
      </>}
      <ConfirmDialog open={leave} danger title="Leave this workspace?" confirmLabel="Leave" loading={leaveM.isPending} description="You lose access to its repositories, reviews and findings." onCancel={() => setLeave(false)} onConfirm={() => leaveM.mutate()} />
      <ConfirmDialog open={del} danger title={`Delete “${ws.name}”?`} confirmLabel="Delete workspace" loading={delM.isPending}
        description="This cannot be undone. Repositories are disconnected and their search index is removed. Type the workspace name to confirm."
        onCancel={() => { setDel(false); setTyped('') }} onConfirm={() => typed === ws.name && delM.mutate()}>
        <input aria-label="Type the workspace name" className={input} value={typed} onChange={(e) => setTyped(e.target.value)} />
      </ConfirmDialog>
    </Card>
  )
}

export default function WorkspacesPage() {
  const { user } = useAuth()
  const { active, isLoading } = useWorkspace()
  return (
    <div className="space-y-4">
      <CreateAndInvitations />
      {isLoading && <Skeleton className="h-40" />}
      {!isLoading && !active && <EmptyState title="No workspace" description="Create a workspace to connect repositories." />}
      {active && (
        <>
          <h2 className="font-pixel text-lg">{active.name} <Badge tone={ROLE_TONE[active.role]}>{active.role}</Badge></h2>
          <General key={active.id} ws={active} />
          <Members ws={active} me={user?.login} />
          <Invitations ws={active} />
          {rank[active.role] >= 2 && <Activity ws={active} />}
          <Danger ws={active} />
        </>
      )}
    </div>
  )
}
