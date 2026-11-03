import { useQuery } from '@tanstack/react-query'
import { Check, ExternalLink, FlaskConical, X } from 'lucide-react'
import { Badge, Card, ErrorState, Skeleton } from '../../components/ui'
import { useToast } from '../../components/ui/Toast'
import { describeError } from '../../lib/api'
import { settingsService } from '../../services'
import ReviewPolicyPanel from './ReviewPolicyPanel'

function Copy({ text }) {
  const { toast } = useToast()
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); toast('Copied to clipboard.', 'success') } catch { toast('Copy failed — select the text and copy it manually.', 'error') }
  }
  return <button type="button" onClick={copy} className="text-xs text-accent-ink hover:underline" aria-label={`Copy ${text}`}>Copy</button>
}

export default function IntegrationsPage() {
  const q = useQuery({ queryKey: ['settings-integrations'], queryFn: settingsService.integrations })
  if (q.isPending) return <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}</div>
  if (q.isError) return <Card><ErrorState message={describeError(q.error)} onRetry={q.refetch} /></Card>
  const d = q.data
  return (
    <div className="space-y-4">
      {(d.demo_login || d.mock_llm || d.vector_backend === 'memory') && (
        <div role="status" className="flex items-start gap-2 rounded-lg border border-accent/40 bg-accent/10 p-3 text-sm">
          <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-accent-ink" aria-hidden />
          <span>Local demo features are active:{d.demo_login ? ' sample-data sign-in;' : ''}{d.mock_llm ? ' mock reviewer (not AI);' : ''}{d.vector_backend === 'memory' ? ' in-memory search store.' : ''} None of these are used when real credentials are configured for production.</span>
        </div>
      )}
      <Card className="p-4">
        <div className="mb-3 flex items-center gap-2"><h2 className="font-semibold">Integration status</h2><Badge className="capitalize">{d.environment}</Badge></div>
        <ul className="divide-y divide-border">
          {d.items.map((i) => (
            <li key={i.key} className="py-3">
              <div className="flex flex-wrap items-center gap-2">
                {i.configured ? <Check className="h-4 w-4 text-ok" aria-hidden /> : <X className="h-4 w-4 text-danger" aria-hidden />}
                <span className="font-medium">{i.label}</span><Badge tone={i.configured ? 'ok' : 'danger'}>{i.configured ? 'Configured' : 'Not configured'}</Badge>
              </div>
              <p className="mt-1 text-sm text-muted">{i.detail}</p>
              {!i.configured && <p className="mt-1 text-xs text-muted">Set in <code>backend/.env</code>: {i.env.map((e) => <code key={e} className="mr-1 rounded bg-surface-2 px-1">{e}</code>)}</p>}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted">Secret values are never shown here, only whether they are set.</p>
      </Card>
      <Card className="space-y-3 p-4">
        <h2 className="font-semibold">GitHub App settings</h2>
        <p className="text-sm text-muted">Enter these in your GitHub App configuration.</p>
        <dl className="space-y-2 text-sm">
          <div><dt className="text-xs font-medium text-muted">Webhook URL</dt><dd className="flex flex-wrap items-center gap-2"><code className="break-all">{d.webhook_url}</code><Copy text={d.webhook_url} /></dd></div>
          <div><dt className="text-xs font-medium text-muted">OAuth callback URL</dt><dd className="flex flex-wrap items-center gap-2"><code className="break-all">{d.oauth_callback_url}</code><Copy text={d.oauth_callback_url} /></dd></div>
          <div><dt className="text-xs font-medium text-muted">Required repository permissions</dt><dd>Contents: Read · Pull requests: Read &amp; write · Metadata: Read</dd></div>
          <div><dt className="text-xs font-medium text-muted">Subscribe to events</dt><dd>Pull request · Push · Installation · Installation repositories</dd></div>
        </dl>
        {d.install_url && <a href={d.install_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-accent-ink hover:underline">Install the GitHub App<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}
      </Card>
      <ReviewPolicyPanel />
    </div>
  )
}
