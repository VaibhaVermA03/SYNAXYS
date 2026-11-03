import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ListChecks, Pencil, Plus, Trash2 } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, SeverityBadge, Skeleton } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { describeError } from '../../lib/api'
import { githubService, ruleService } from '../../services'
import RuleDialog from './RuleDialog'

export default function RulesPage() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const [dialog, setDialog] = useState(null) // null | {rule?}
  const [del, setDel] = useState(null)
  const rules = useQuery({ queryKey: ['rules'], queryFn: () => ruleService.list() })
  const repos = useQuery({ queryKey: ['repositories', 'owner-scope'], queryFn: () => githubService.repositories({ page_size: 100 }) })
  const ownerRepos = (repos.data?.items || []).filter((r) => r.role === 'owner')
  const refresh = () => qc.invalidateQueries({ queryKey: ['rules'] })

  const toggle = useMutation({ mutationFn: (r) => ruleService.update(r.id, { enabled: !r.enabled }), onSuccess: refresh, onError: (e) => toast(describeError(e), 'error') })
  const remove = useMutation({
    mutationFn: (r) => ruleService.remove(r.id),
    onSuccess: () => { toast('Rule deleted.', 'success'); setDel(null); refresh() },
    onError: (e) => { toast(describeError(e), 'error'); setDel(null) },
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="flex-1 text-sm text-muted">Custom instructions the AI reviewer applies in addition to its built-in checks. They are treated as untrusted input and cannot override security policy.</p>
        <Button onClick={() => setDialog({})}><Plus className="h-4 w-4" aria-hidden />New rule</Button>
      </div>
      <Card>
        {rules.isPending && <div className="space-y-2 p-4">{[0, 1].map((i) => <Skeleton key={i} className="h-16" />)}</div>}
        {rules.isError && <ErrorState message={describeError(rules.error)} onRetry={rules.refetch} />}
        {rules.data?.length === 0 && <EmptyState icon={ListChecks} title="No custom rules yet" description="Create a rule such as “Flag SQL built with string concatenation”." />}
        {rules.data?.length > 0 && (
          <ul className="divide-y divide-border">
            {rules.data.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{r.name}</span><SeverityBadge severity={r.severity} />
                    <Badge>{r.repository || 'All my repositories'}</Badge>
                    {r.is_demo && <Badge tone="accent">Demo</Badge>}
                    {!r.enabled && <Badge tone="warn">Disabled</Badge>}
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm text-muted">{r.instruction}</p>
                  {(r.languages.length > 0 || r.file_patterns.length > 0) && <p className="mt-1 font-mono text-xs text-muted">{[...r.languages, ...r.file_patterns].join(' · ')}</p>}
                </div>
                {r.editable ? (
                  <div className="flex gap-2">
                    <Button variant="secondary" size="sm" onClick={() => toggle.mutate(r)} aria-label={`${r.enabled ? 'Disable' : 'Enable'} ${r.name}`}>{r.enabled ? 'Disable' : 'Enable'}</Button>
                    <Button variant="secondary" size="sm" onClick={() => setDialog({ rule: r })} aria-label={`Edit ${r.name}`}><Pencil className="h-3.5 w-3.5" aria-hidden /></Button>
                    <Button variant="secondary" size="sm" onClick={() => setDel(r)} aria-label={`Delete ${r.name}`}><Trash2 className="h-3.5 w-3.5" aria-hidden /></Button>
                  </div>
                ) : <span className="text-xs text-muted">Read-only (created by another user)</span>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {dialog && <RuleDialog rule={dialog.rule} repositories={ownerRepos} onClose={() => setDialog(null)} />}
      <ConfirmDialog open={!!del} danger title={`Delete “${del?.name}”?`} confirmLabel="Delete" loading={remove.isPending}
        description="Future reviews will no longer apply this rule. Past review results are not changed." onCancel={() => setDel(null)} onConfirm={() => remove.mutate(del)} />
    </div>
  )
}
