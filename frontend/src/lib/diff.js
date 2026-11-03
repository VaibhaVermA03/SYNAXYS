// Pure helpers for the diff viewer (unit-tested).

/** Pair removed/added lines side by side; context lines appear on both sides. */
export function toSplitRows(lines) {
  const rows = []
  let dels = []
  let adds = []
  const flush = () => {
    const n = Math.max(dels.length, adds.length)
    for (let i = 0; i < n; i++) rows.push({ left: dels[i] || null, right: adds[i] || null })
    dels = []
    adds = []
  }
  for (const l of lines) {
    if (l.kind === 'del') dels.push(l)
    else if (l.kind === 'add') adds.push(l)
    else { flush(); rows.push({ left: l, right: l }) }
  }
  flush()
  return rows
}

/** Findings that may be shown inline, keyed by the (new-file) line they end on. */
export function inlineFindingsByLine(findings, path) {
  const map = new Map()
  for (const f of findings || []) {
    if (!f.inline_possible || f.path !== path || f.end_line == null) continue
    map.set(f.end_line, [...(map.get(f.end_line) || []), f])
  }
  return map
}

export const fileAnchor = (path) => `file-${path.replace(/[^a-zA-Z0-9]/g, '-')}`

/** Nested tree from flat paths; folders first, alphabetical. */
export function buildFileTree(paths) {
  const root = { children: [] }
  for (const full of paths) {
    let node = root
    const parts = full.split('/')
    parts.forEach((name, i) => {
      const isFile = i === parts.length - 1
      let child = node.children.find((c) => c.name === name && !!c.children === !isFile)
      if (!child) {
        child = isFile ? { name, path: full } : { name, children: [] }
        node.children.push(child)
      }
      node = child
    })
  }
  const sort = (n) => {
    if (!n.children) return
    n.children.sort((a, b) => (!!b.children - !!a.children) || a.name.localeCompare(b.name))
    n.children.forEach(sort)
  }
  sort(root)
  return root.children
}

export const CATEGORY_LABELS = {
  bug: 'Bugs & correctness', security: 'Security', performance: 'Performance', maintainability: 'Maintainability & style', testing: 'Testing',
}
export const CATEGORY_ORDER = ['security', 'bug', 'performance', 'maintainability', 'testing']
