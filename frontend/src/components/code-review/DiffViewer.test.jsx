import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DiffViewer from './DiffViewer'

const line = (kind, old_no, new_no, text) => ({ kind, old_no, new_no, text })
const files = [
  { path: 'app/users.py', status: 'modified', additions: 2, deletions: 1, skipped_reason: null, previous_path: null,
    hunks: [{ header: '@@ -10,2 +10,3 @@', lines: [line('context', 10, 10, 'cur = db.cursor()'), line('del', 11, null, 'cur.execute(sql, (n,))'), line('add', null, 11, 'cur.execute("..." + n)'), line('add', null, 12, 'return cur')] }] },
  { path: 'logo.png', status: 'added', additions: 0, deletions: 0, skipped_reason: 'binary', previous_path: null, hunks: [] },
  { path: 'big.py', status: 'modified', additions: 900, deletions: 1, skipped_reason: 'patch_unavailable', previous_path: null, hunks: [] },
]
const finding = { id: 7, category: 'security', severity: 'high', title: 'SQL injection', explanation: 'Concatenation', evidence: 'cur.execute("..." + n)', path: 'app/users.py',
  start_line: 11, end_line: 11, remediation: null, patch: null, confidence: 0.9, confidence_label: 'high', inline_possible: true, status: 'open', comment: null }

describe('DiffViewer', () => {
  it('renders line numbers, additions/deletions and file stats', () => {
    render(<DiffViewer files={files} findings={[]} />)
    const table = screen.getByRole('table', { name: /diff of app\/users.py/i })
    expect(within(table).getByText('+cur.execute("..." + n)')).toBeInTheDocument()
    expect(within(table).getByText('-cur.execute(sql, (n,))')).toBeInTheDocument()
    expect(screen.getByText('+2')).toBeInTheDocument()
  })

  it('attaches an inline finding under its line and labels it as an AI suggestion', () => {
    render(<DiffViewer files={files} findings={[finding]} />)
    const card = screen.getByRole('article', { name: /high finding: SQL injection/i })
    expect(card).toHaveTextContent(/AI suggestion/)
    const rows = screen.getAllByRole('row')
    const lineRow = rows.findIndex((r) => r.textContent.includes('+cur.execute("..." + n)'))
    expect(rows[lineRow + 1]).toContainElement(card)                              // directly after the changed line
  })

  it('does not attach summary-only findings to the diff', () => {
    render(<DiffViewer files={files} findings={[{ ...finding, inline_possible: false }]} />)
    expect(screen.queryByRole('article')).not.toBeInTheDocument()
  })

  it('switches to split layout', async () => {
    render(<DiffViewer files={files} findings={[]} />)
    await userEvent.click(screen.getByRole('button', { name: /split/i }))
    expect(screen.getByRole('button', { name: /split/i })).toHaveAttribute('aria-pressed', 'true')
    const row = screen.getAllByRole('row').find((r) => r.textContent.includes('cur.execute(sql, (n,))'))
    expect(row.textContent).toContain('+cur.execute("..." + n)')                  // deletion and addition share a row
  })

  it('explains files that cannot be shown instead of hiding them', () => {
    render(<DiffViewer files={files} findings={[]} />)
    expect(screen.getByText(/binary file/i)).toBeInTheDocument()
    expect(screen.getByText(/did not provide a diff/i)).toBeInTheDocument()
  })
})
