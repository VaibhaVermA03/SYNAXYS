import { Fragment } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, TriangleAlert } from 'lucide-react'
import Logo from '../../components/layout/Logo'
import ThemeToggle from '../../components/layout/ThemeToggle'
import NotFoundPage from '../../pages/NotFoundPage'
import LegalFooter from './LegalFooter'
import privacy from '../../legal/privacy.json'
import terms from '../../legal/terms.json'
import security from '../../legal/security.json'
import license from '../../legal/license.json'
import operator from '../../legal/operator.json'

export const DOCS = { privacy, terms, security, license }

// The owner's real details live in ONE file (src/legal/operator.json); "{{key}}" in the documents is replaced by its value.
export const fillOperator = (text) => text.replace(/\{\{(\w+)\}\}/g, (m, k) => (!k.startsWith('_') && Object.hasOwn(operator, k) ? String(operator[k]) : m))

// True while a document still contains an unfilled "[[...]]" value; the draft notice is shown only then.
export function hasUnfilled(doc) {
  const walk = (x) => {
    if (typeof x === 'string') return /\[\[.+?\]\]/.test(fillOperator(x))
    if (Array.isArray(x)) return x.some(walk)
    if (x && typeof x === 'object') return Object.values(x).some(walk)
    return false
  }
  return walk([doc.effective, doc.sections])
}

// "[[text]]" marks information only the operator can provide; it is shown highlighted so nothing placeholder-like is mistaken for a real value.
function Inline({ text }) {
  return fillOperator(text).split(/(\[\[.+?\]\])/g).map((part, i) => (/^\[\[.+\]\]$/.test(part)
    ? <mark key={i} className="rounded bg-warn/20 px-1 text-fg" title="To be provided by the operator">[{part.slice(2, -2)}]</mark>
    : <Fragment key={i}>{part}</Fragment>))
}

function Block({ b }) {
  if (b.p) return <p className="leading-relaxed"><Inline text={b.p} /></p>
  if (b.note) return <p role="note" className="rounded-lg border border-accent/30 bg-accent/10 p-3 font-medium"><Inline text={b.note} /></p>
  if (b.ul) return <ul className="list-disc space-y-1 pl-5">{b.ul.map((i, k) => <li key={k}><Inline text={i} /></li>)}</ul>
  if (b.table) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] border-collapse text-left text-xs sm:text-sm">
          <thead><tr>{b.table.head.map((h) => <th key={h} scope="col" className="border-b border-border px-2 py-1.5 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{b.table.rows.map((r, i) => <tr key={i} className="align-top">{r.map((c, k) => <td key={k} className="border-b border-border/60 px-2 py-1.5"><Inline text={c} /></td>)}</tr>)}</tbody>
        </table>
      </div>
    )
  }
  return null
}

export function LegalDocument({ doc }) {
  return (
    <article className="space-y-6 text-sm">
      <header className="space-y-3">
        <h1 className="text-2xl">{doc.title}</h1>
        {doc.banner && hasUnfilled(doc) && <div role="alert" className="flex gap-2 rounded-lg border border-warn/40 bg-warn/10 p-3 text-xs"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /><p><Inline text={doc.banner} /></p></div>}
        {doc.effective && <p className="text-muted"><Inline text={doc.effective} /></p>}
      </header>
      <nav aria-label="Contents" className="rounded-lg border border-border p-3 text-xs">
        <ol className="grid gap-1 sm:grid-cols-2">{doc.sections.map((s) => <li key={s.id}><a className="text-accent-ink hover:underline" href={`#${s.id}`}>{s.title}</a></li>)}</ol>
      </nav>
      {doc.sections.map((s) => (
        <section key={s.id} id={s.id} aria-labelledby={`${s.id}-h`} className="scroll-mt-4 space-y-3">
          <h2 id={`${s.id}-h`} className="text-lg">{s.title}</h2>
          {s.blocks.map((b, i) => <Block key={i} b={b} />)}
        </section>
      ))}
    </article>
  )
}

// Public page (no sign-in needed): /legal/privacy | terms | security | license
export default function LegalPage() {
  const { doc } = useParams()
  const d = Object.hasOwn(DOCS, doc) ? DOCS[doc] : null
  if (!d) return <div className="mx-auto max-w-xl p-6"><NotFoundPage /></div>
  return (
    <div className="min-h-dvh bg-bg text-fg">
      <header className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-4">
        <Link to="/" aria-label="SYNAXYS home"><Logo size="md" /></Link>
        <div className="flex items-center gap-2">
          <Link to="/app/dashboard" className="inline-flex items-center gap-1 text-xs text-accent-ink hover:underline"><ArrowLeft className="h-3 w-3" aria-hidden />Back to the app</Link>
          <ThemeToggle align="end" />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-10"><LegalDocument doc={d} /></main>
      <LegalFooter className="mx-auto max-w-3xl px-4 pb-8" />
    </div>
  )
}