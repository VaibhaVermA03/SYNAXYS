import { useState } from 'react'
import { Columns2, Rows3 } from 'lucide-react'
import { Badge, Button, Card } from '../ui'
import FindingCard from './FindingCard'
import { fileAnchor, inlineFindingsByLine, toSplitRows } from '../../lib/diff'

const SKIP_TEXT = {
  binary: 'Binary file — not shown or reviewed.',
  patch_unavailable: 'GitHub did not provide a diff for this file (it is probably too large). It was not reviewed.',
  too_large: 'This file’s diff exceeds the configured size limit and was not reviewed.',
  no_content_change: 'File renamed without content changes.',
}
const ROW = { add: 'bg-ok/10', del: 'bg-danger/10', context: '' }
const SIGN = { add: '+', del: '-', context: ' ' }

const Num = ({ n }) => <td className="w-12 select-none px-2 text-right text-muted">{n ?? ''}</td>
const Code = ({ l, className = '' }) => <td className={`whitespace-pre px-2 ${l ? ROW[l.kind] : 'bg-surface-2/50'} ${className}`}>{l ? `${SIGN[l.kind]}${l.text}` : ''}</td>

function Unified({ hunk, byLine, cols }) {
  return hunk.lines.map((l, i) => (
    <FragmentRows key={i} cols={cols} findings={l.new_no != null && l.kind !== 'del' ? byLine.get(l.new_no) : null}>
      <tr className={ROW[l.kind]}><Num n={l.old_no} /><Num n={l.new_no} /><td className="whitespace-pre px-2">{`${SIGN[l.kind]}${l.text}`}</td></tr>
    </FragmentRows>
  ))
}

function Split({ hunk, byLine, cols }) {
  return toSplitRows(hunk.lines).map((r, i) => (
    <FragmentRows key={i} cols={cols} findings={r.right && r.right.kind !== 'del' ? byLine.get(r.right.new_no) : null}>
      <tr><Num n={r.left?.old_no} /><Code l={r.left} className="w-1/2 border-r border-border" /><Num n={r.right?.new_no} /><Code l={r.right} className="w-1/2" /></tr>
    </FragmentRows>
  ))
}

function FragmentRows({ children, findings, cols }) {
  return (
    <>
      {children}
      {findings?.map((f) => <tr key={f.id}><td colSpan={cols} className="bg-surface px-3 py-2 font-sans"><FindingCard finding={f} compact /></td></tr>)}
    </>
  )
}

export default function DiffViewer({ files, findings }) {
  const [mode, setMode] = useState('unified')
  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2" role="group" aria-label="Diff layout">
        <Button size="sm" variant={mode === 'unified' ? 'primary' : 'secondary'} aria-pressed={mode === 'unified'} onClick={() => setMode('unified')}><Rows3 className="h-4 w-4" aria-hidden />Unified</Button>
        <Button size="sm" variant={mode === 'split' ? 'primary' : 'secondary'} aria-pressed={mode === 'split'} onClick={() => setMode('split')}><Columns2 className="h-4 w-4" aria-hidden />Split</Button>
      </div>
      {files.map((file) => {
        const byLine = inlineFindingsByLine(findings, file.path)
        const cols = mode === 'split' ? 4 : 3
        return (
          <Card key={file.path} className="overflow-hidden" id={fileAnchor(file.path)}>
            <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface-2 px-3 py-2 text-sm">
              <span className="font-mono font-medium">{file.previous_path ? `${file.previous_path} → ${file.path}` : file.path}</span>
              <Badge className="capitalize">{file.status}</Badge>
              <span className="ml-auto text-xs"><span className="text-ok">+{file.additions}</span> <span className="text-danger">−{file.deletions}</span></span>
            </div>
            {file.skipped_reason ? <p className="p-3 text-sm text-muted">{SKIP_TEXT[file.skipped_reason] || 'This file is not shown.'}</p> : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse font-mono text-xs" aria-label={`Diff of ${file.path}`}>
                  <tbody>
                    {file.hunks.map((h, i) => (
                      <HunkRows key={i} hunk={h} mode={mode} byLine={byLine} cols={cols} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )
      })}
    </div>
  )
}

function HunkRows({ hunk, mode, byLine, cols }) {
  return (
    <>
      <tr><td colSpan={cols} className="bg-accent/5 px-2 py-1 text-muted">{hunk.header}</td></tr>
      {mode === 'split' ? <Split hunk={hunk} byLine={byLine} cols={cols} /> : <Unified hunk={hunk} byLine={byLine} cols={cols} />}
    </>
  )
}
