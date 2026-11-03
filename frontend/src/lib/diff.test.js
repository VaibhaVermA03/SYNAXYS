import { describe, expect, it } from 'vitest'
import { buildFileTree, fileAnchor, inlineFindingsByLine, toSplitRows } from './diff'

const L = (kind, old_no, new_no, text = '') => ({ kind, old_no, new_no, text })

describe('toSplitRows', () => {
  it('pairs removed/added lines and mirrors context', () => {
    const rows = toSplitRows([L('context', 1, 1, 'a'), L('del', 2, null, 'b'), L('del', 3, null, 'c'), L('add', null, 2, 'B'), L('context', 4, 3, 'd')])
    expect(rows).toHaveLength(4)
    expect(rows[1]).toMatchObject({ left: { old_no: 2 }, right: { new_no: 2 } })
    expect(rows[2]).toMatchObject({ left: { old_no: 3 }, right: null })      // unmatched deletion
    expect(rows[0].left).toBe(rows[0].right)
  })
  it('handles pure additions', () => {
    expect(toSplitRows([L('add', null, 1), L('add', null, 2)]).every((r) => r.left === null && r.right)).toBe(true)
  })
})

describe('inlineFindingsByLine', () => {
  const f = (o) => ({ id: 1, path: 'a.py', end_line: 5, inline_possible: true, ...o })
  it('keeps only inline-capable findings for the file, keyed by end line', () => {
    const m = inlineFindingsByLine([f({}), f({ id: 2, inline_possible: false }), f({ id: 3, path: 'b.py' }), f({ id: 4, end_line: null })], 'a.py')
    expect([...m.keys()]).toEqual([5]); expect(m.get(5)).toHaveLength(1)
  })
})

describe('buildFileTree', () => {
  it('nests paths with folders first', () => {
    const t = buildFileTree(['z.md', 'src/b.js', 'src/a.js', 'src/lib/x.js'])
    expect(t.map((n) => n.name)).toEqual(['src', 'z.md'])
    expect(t[0].children.map((n) => n.name)).toEqual(['lib', 'a.js', 'b.js'])
  })
  it('anchors are DOM-safe', () => { expect(fileAnchor('a/b c.py')).toBe('file-a-b-c-py') })
})
