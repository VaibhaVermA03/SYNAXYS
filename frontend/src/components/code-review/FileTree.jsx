import { FileCode2, Folder } from 'lucide-react'
import { buildFileTree } from '../../lib/diff'

function Node({ node, depth, onSelect, counts, active }) {
  const pad = { paddingLeft: `${depth * 12 + 8}px` }
  if (node.children) {
    return (
      <li>
        <div style={pad} className="flex items-center gap-1.5 py-1 text-xs text-muted"><Folder className="h-3.5 w-3.5" aria-hidden />{node.name}</div>
        <ul>{node.children.map((c) => <Node key={c.name + (c.path || '')} node={c} depth={depth + 1} onSelect={onSelect} counts={counts} active={active} />)}</ul>
      </li>
    )
  }
  return (
    <li>
      <button style={pad} onClick={() => onSelect(node.path)} aria-current={active === node.path ? 'true' : undefined}
        className={`flex w-full items-center gap-1.5 rounded py-1 pr-2 text-left text-xs hover:bg-surface-2 ${active === node.path ? 'bg-accent/10 text-accent-ink' : ''}`}>
        <FileCode2 className="h-3.5 w-3.5 shrink-0" aria-hidden /><span className="truncate">{node.name}</span>
        {counts[node.path] > 0 && <span className="ml-auto rounded-full bg-warn/20 px-1.5 text-[10px] font-medium text-warn" aria-label={`${counts[node.path]} findings`}>{counts[node.path]}</span>}
      </button>
    </li>
  )
}

export default function FileTree({ files, findings, active, onSelect }) {
  const counts = {}
  for (const f of findings || []) counts[f.path] = (counts[f.path] || 0) + 1
  const tree = buildFileTree(files.map((f) => f.path))
  return <nav aria-label="Changed files"><ul>{tree.map((n) => <Node key={n.name + (n.path || '')} node={n} depth={0} onSelect={onSelect} counts={counts} active={active} />)}</ul></nav>
}
