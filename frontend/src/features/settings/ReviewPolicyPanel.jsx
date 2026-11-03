import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck, TriangleAlert } from 'lucide-react'
import { Button, Card, ConfirmDialog, EmptyState, ErrorState, Input, Select, Skeleton } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { describeError } from '../../lib/api'
import { githubService, repoConfigService } from '../../services'

const ACTIONS = [['opened', 'Pull request opened'], ['synchronize', 'New commits pushed'], ['reopened', 'Pull request reopened']]

export default function ReviewPolicyPanel() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const repos = useQuery({ queryKey: ['repositories', 'policy-scope'], queryFn: () => githubService.repositories({ page_size: 100 }) })
  const adminRepos = (repos.data?.items || []).filter((r) => r.role === 'owner' && !r.is_demo)
  const [repoId, setRepoId] = useState('')
  const [form, setForm] = useState(null)
  const [confirmAuto, setConfirmAuto] = useState(false)
  const selected = repoId || (adminRepos[0] ? String(adminRepos[0].id) : '')

  const cfg = useQuery({ queryKey: ['repo-config', selected], queryFn: () => repoConfigService.get(selected), enabled: !!selected })
  useEffect(() => { if (cfg.data) setForm({ mode: cfg.data.auto_publish ? 'auto' : 'manual', allowed_actions: cfg.data.allowed_actions, max_files: cfg.data.max_files, max_patch_bytes: cfg.data.max_patch_bytes, index_enabled: cfg.data.index_enabled }) }, [cfg.data])

  const save = useMutation({
    mutationFn: () => repoConfigService.update(selected, {
      ...(form.mode === 'auto' ? { auto_publish: true } : { require_approval: true }),
      allowed_actions: form.allowed_actions, max_files: Number(form.max_files), max_patch_bytes: Number(form.max_patch_bytes), index_enabled: form.index_enabled }),
    onSuccess: (data) => { toast('Review policy saved.', 'success'); setConfirmAuto(false); qc.setQueryData(['repo-config', selected], data); qc.invalidateQueries({ queryKey: ['settings-audit'] }) },
    onError: (e) => { toast(describeError(e), 'error'); setConfirmAuto(false) },
  })
  const onSave = () => (form.mode === 'auto' && !cfg.data.auto_publish ? setConfirmAuto(true) : save.mutate())
  const set = (patch) => setForm((f) => ({ ...f, ...patch }))
  const toggleAction = (a) => set({ allowed_actions: form.allowed_actions.includes(a) ? form.allowed_actions.filter((x) => x !== a) : [...form.allowed_actions, a] })

  if (repos.isPending) return <Skeleton className="h-40" />
  if (repos.isError) return <Card><ErrorState message={describeError(repos.error)} onRetry={repos.refetch} /></Card>
  if (adminRepos.length === 0) return <Card><EmptyState icon={ShieldCheck} title="No repositories to configure" description="Review policy can be changed by GitHub admins of a repository. Sync your repositories first." /></Card>

  return (
    <Card className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="flex items-center gap-2 font-semibold"><ShieldCheck className="h-4 w-4" aria-hidden />Review policy</h2>
        <Select ariaLabel="Repository" className="w-full sm:ml-auto sm:w-64" value={selected} onChange={(v) => { setForm(null); setRepoId(v) }}
          options={adminRepos.map((r) => ({ value: String(r.id), label: r.full_name }))} />
      </div>
      {cfg.isPending && <Skeleton className="h-40" />}
      {cfg.isError && <ErrorState message={describeError(cfg.error)} onRetry={cfg.refetch} />}
      {form && (
        <form onSubmit={(e) => { e.preventDefault(); onSave() }} className="space-y-4" noValidate>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Publishing mode</legend>
            <label className="flex items-start gap-2 text-sm"><input type="radio" name="mode" checked={form.mode === 'manual'} onChange={() => set({ mode: 'manual' })} />
              <span><strong>Manual approval</strong> (recommended) — a repository admin approves each comment before it is posted.</span></label>
            <label className="flex items-start gap-2 text-sm"><input type="radio" name="mode" checked={form.mode === 'auto'} onChange={() => set({ mode: 'auto' })} />
              <span><strong>Auto-publish</strong> — verified comments are posted to GitHub automatically after each review, without human approval.</span></label>
            <p className="text-xs text-muted">Comments are always posted as comment-only reviews. SYNAXYS never approves or requests changes on a pull request.</p>
          </fieldset>
          <fieldset className="space-y-1"><legend className="text-sm font-medium">Review these pull request events</legend>
            {ACTIONS.map(([a, label]) => <label key={a} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.allowed_actions.includes(a)} onChange={() => toggleAction(a)} />{label}</label>)}
          </fieldset>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm"><span className="mb-1 block font-medium">Max changed files per review</span><Input type="number" min={1} max={200} value={form.max_files} onChange={(e) => set({ max_files: e.target.value })} /></label>
            <label className="block text-sm"><span className="mb-1 block font-medium">Max patch size per file (bytes)</span><Input type="number" min={10000} max={1000000} step={1000} value={form.max_patch_bytes} onChange={(e) => set({ max_patch_bytes: e.target.value })} /></label>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.index_enabled} onChange={(e) => set({ index_enabled: e.target.checked })} />Index this repository for code search and review context</label>
          <Button type="submit" loading={save.isPending} disabled={form.allowed_actions.length === 0} title={form.allowed_actions.length === 0 ? 'Select at least one event' : undefined}>Save policy</Button>
        </form>
      )}
      <ConfirmDialog open={confirmAuto} danger title="Enable auto-publish?" confirmLabel="Enable auto-publish" loading={save.isPending}
        description="After every review, SYNAXYS will post its AI-generated comments to GitHub without anyone approving them. They are suggestions and can be wrong. Only enable this if your team accepts that. This change is recorded in the audit log."
        onCancel={() => setConfirmAuto(false)} onConfirm={() => save.mutate()} />
      {form?.mode === 'auto' && cfg.data?.auto_publish && <p role="status" className="flex items-center gap-2 text-xs text-warn"><TriangleAlert className="h-3.5 w-3.5" aria-hidden />Auto-publish is currently enabled for this repository.</p>}
    </Card>
  )
}
