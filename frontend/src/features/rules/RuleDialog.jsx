import { useEffect, useRef, useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Input, Select } from '../../components/ui'
import FindingCard from '../../components/code-review/FindingCard'
import { useToast } from '../../components/ui/Toast'
import { ApiError, describeError } from '../../lib/api'
import { ruleService } from '../../services'

const schema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(120, 'At most 120 characters'),
  description: z.string().max(500, 'At most 500 characters'),
  instruction: z.string().trim().min(10, 'Describe what to look for (at least 10 characters)').max(2000, 'At most 2000 characters'),
  severity: z.enum(['critical', 'high', 'medium', 'low', 'info']),
  languages: z.string(),
  file_patterns: z.string(),
  repository_id: z.string(),
  enabled: z.boolean(),
})
const list = (s) => s.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean)
const Field = ({ label, error, children, hint, as: Tag = 'label' }) => (
  <Tag className="block text-sm">
    <span className="mb-1 block font-medium">{label}</span>{children}
    {hint && !error && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    {error && <span role="alert" className="mt-1 block text-xs text-danger">{error}</span>}
  </Tag>
)

export default function RuleDialog({ rule, repositories, onClose }) {
  const qc = useQueryClient()
  const { toast } = useToast()
  const editing = !!rule
  const first = useRef(null)
  const [fileName, setFileName] = useState('snippet.py')
  const [code, setCode] = useState('')
  const { register, control, handleSubmit, setError, getValues, formState: { errors } } = useForm({
    resolver: zodResolver(schema),
    defaultValues: { name: rule?.name ?? '', description: rule?.description ?? '', instruction: rule?.instruction ?? '', severity: rule?.severity ?? 'medium',
      languages: (rule?.languages ?? []).join(', '), file_patterns: (rule?.file_patterns ?? []).join('\n'), repository_id: rule?.repository_id ? String(rule.repository_id) : '', enabled: rule?.enabled ?? true },
  })
  useEffect(() => {
    first.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const save = useMutation({
    mutationFn: (v) => {
      const body = { name: v.name, description: v.description, instruction: v.instruction, severity: v.severity, enabled: v.enabled, languages: list(v.languages), file_patterns: list(v.file_patterns) }
      return editing ? ruleService.update(rule.id, body) : ruleService.create({ ...body, repository_id: v.repository_id ? Number(v.repository_id) : null })
    },
    onSuccess: () => { toast(editing ? 'Rule updated.' : 'Rule created.', 'success'); qc.invalidateQueries({ queryKey: ['rules'] }); onClose() },
    onError: (e) => {
      if (e instanceof ApiError && e.fields?.length) e.fields.forEach((f) => setError(f.loc[0], { message: f.msg }))
      else toast(describeError(e), 'error')
    },
  })
  const test = useMutation({
    mutationFn: () => {
      const v = getValues()
      return ruleService.test({ instruction: v.instruction.trim(), severity: v.severity, file_name: fileName.trim() || 'snippet.py', code })
    },
  })
  const canTest = code.trim().length > 0
  const { ref: nameRef, ...nameProps } = register('name')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/50 p-4">
      <form role="dialog" aria-modal="true" aria-labelledby="rule-title" onSubmit={handleSubmit((v) => save.mutate(v))} noValidate
        className="w-full max-w-lg space-y-4 rounded-xl border border-border bg-surface p-5 shadow-xl">
        <h2 id="rule-title" className="text-lg font-semibold">{editing ? 'Edit rule' : 'New review rule'}</h2>
        <p className="text-xs text-muted">Rules describe what to look for in code. They cannot change security policies; instructions that try to are rejected.</p>
        <Field label="Name" error={errors.name?.message}><Input {...nameProps} ref={(el) => { nameRef(el); first.current = el }} /></Field>
        <Field label="Description" error={errors.description?.message}><Input {...register('description')} /></Field>
        <Field label="Instruction" error={errors.instruction?.message} hint="e.g. Flag SQL built with string concatenation or f-strings.">
          <textarea {...register('instruction')} rows={4} className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm" />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field as="div" label="Severity" error={errors.severity?.message}>
            <Controller name="severity" control={control} render={({ field }) => (
              <Select ariaLabel="Severity" value={field.value} onChange={field.onChange} options={['critical', 'high', 'medium', 'low', 'info'].map((v) => ({ value: v, label: v }))} />
            )} />
          </Field>
          <Field as="div" label="Repository scope" error={errors.repository_id?.message}>
            <Controller name="repository_id" control={control} render={({ field }) => (
              <Select ariaLabel="Repository scope" disabled={editing} value={field.value} onChange={field.onChange}
                options={[{ value: '', label: 'All my repositories' }, ...repositories.map((r) => ({ value: String(r.id), label: r.full_name }))]} />
            )} />
          </Field>
        </div>
        <Field label="Languages" error={errors.languages?.message} hint="Comma separated, e.g. python, typescript. Empty = all."><Input {...register('languages')} /></Field>
        <Field label="File patterns" error={errors.file_patterns?.message} hint="One per line or comma separated, e.g. src/**/*.py. Empty = all files.">
          <textarea {...register('file_patterns')} rows={2} className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs" />
        </Field>
        <section aria-labelledby="rule-test-title" className="space-y-2 rounded-lg border border-border p-3">
          <h3 id="rule-test-title" className="text-sm font-semibold">Test this rule</h3>
          <p className="text-xs text-muted">Runs the rule once against the code you paste. Nothing is saved or sent to GitHub.</p>
          <Input aria-label="Test file name" value={fileName} onChange={(e) => setFileName(e.target.value)} placeholder="snippet.py" />
          <textarea aria-label="Test code" value={code} onChange={(e) => setCode(e.target.value)} rows={5} placeholder="Paste a code snippet…"
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs" />
          <Button type="button" variant="secondary" size="sm" disabled={!canTest} loading={test.isPending} onClick={() => test.mutate()}>Run test</Button>
          {test.isError && <p role="alert" className="text-sm text-danger">{test.error.code === 'openai_not_configured' ? 'No AI provider is configured on this server (set OPENAI_API_KEY).' : describeError(test.error)}</p>}
          {test.data && (
            <div className="space-y-2" aria-live="polite">
              {test.data.mock && <p className="rounded-md bg-warn/10 p-2 text-xs"><Badge tone="warn">Mock model</Badge> Deterministic keyword matcher, not AI — results do not reflect a real review.</p>}
              {test.data.findings.length === 0 ? <p className="text-sm text-muted">No findings for this snippet. {test.data.mock ? '' : 'That is not a guarantee the rule is correct or the code is safe.'}</p>
                : test.data.findings.map((f) => <FindingCard key={f.id} finding={f} compact />)}
            </div>
          )}
        </section>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" {...register('enabled')} />Enabled</label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending}>{editing ? 'Save changes' : 'Create rule'}</Button>
        </div>
      </form>
    </div>
  )
}
