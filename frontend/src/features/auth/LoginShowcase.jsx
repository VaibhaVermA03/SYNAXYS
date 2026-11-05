import { Check, GitPullRequest } from 'lucide-react'
import AmbientBackground from './AmbientBackground'

const Line = ({ n, children, add }) => (
  <div className={`flex gap-3 px-3 ${add ? 'bg-ok/15' : ''}`}>
    <span className="w-5 shrink-0 select-none text-right text-muted">{n}</span>
    <span className="whitespace-pre">{children}</span>
  </div>
)

/** Right half of the login page (desktop only). Decorative and illustrative: the pull request below is an example, not real data. */
export default function LoginShowcase() {
  return (
    <section aria-hidden="true" className="relative hidden overflow-y-auto overflow-x-hidden border-l border-border bg-surface-2/40 lg:flex">
      <AmbientBackground />
      <div className="relative z-10 m-auto w-full max-w-xl px-10 py-8">
        <p className="font-pixel text-xs uppercase tracking-[0.22em] text-muted">AI code review</p>
        <h2 className="mt-3 font-pixel text-3xl leading-tight xl:text-4xl">Smarter Reviews.<br />Safer Code.</h2>
        {/* <p className="mt-4 max-w-md text-sm text-muted [@media(max-height:680px)]:hidden">Evidence-backed findings on every pull request. You decide what gets posted to GitHub.</p> */}

        <div className="mt-8 space-y-3">
          <div className="animate-reveal rounded-2xl border border-border bg-surface p-4 shadow-lg" style={{ animationDelay: '100ms' }}>
            <div className="flex items-center gap-2 text-xs text-muted"><GitPullRequest className="h-4 w-4" strokeWidth={1.5} />alice/shop #7 · feat/lookup → main</div>
            <p className="mt-2 font-pixel text-sm">Add user lookup by name</p>
            <div className="mt-3 overflow-hidden rounded-lg bg-surface-2 py-1 font-mono text-[11px] leading-5">
              <Line n={10}>cur = db.cursor()</Line>
              <Line n={11} add>+ q = "SELECT * FROM u WHERE n='" + n</Line>
              <Line n={12} add>+ cur.execute(q)<span className="ml-0.5 inline-block h-3 w-1.5 animate-blink bg-fg align-middle" /></Line>
            </div>
          </div>

          <div className="ml-10 animate-reveal" style={{ animationDelay: '500ms' }}>
            <div className="animate-float rounded-2xl border border-border bg-surface p-4 shadow-lg">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded-full bg-danger/10 px-2 py-0.5 font-medium text-danger">High</span>
                <span className="rounded-full bg-accent/10 px-2 py-0.5 font-medium text-accent-ink">AI suggestion</span>
                <span className="text-muted">Confidence 90%</span>
              </div>
              <p className="mt-2 text-sm font-medium">SQL built by string concatenation</p>
              <p className="mt-1 text-xs text-muted">User input reaches the query unescaped. Use a parameterized query instead.</p>
              <p className="mt-2 text-[10px] uppercase tracking-widest text-muted">Illustrative example</p>
            </div>
          </div>

          <div className="-ml-2 w-72 animate-reveal [@media(max-height:780px)]:hidden" style={{ animationDelay: '900ms' }}>
            <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface px-4 py-3 shadow-lg">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ok/15 text-ok"><Check className="h-4 w-4" strokeWidth={2} /></span>
              <div><p className="text-sm font-medium">Approved by an admin</p><p className="text-xs text-muted">Posted as a comment-only review</p></div>
            </div>
          </div>
        </div>

      </div>
    </section>
  )
}
