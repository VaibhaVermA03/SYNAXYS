import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import LegalPage, { DOCS, fillOperator, hasUnfilled } from './LegalPage'
import LegalFooter, { LEGAL_LINKS } from './LegalFooter'
import { renderApp } from '../../test/utils'

// Phase 5 (batch 17): public legal pages and footer links. NOT RUN in the authoring sandbox.
const page = (doc) => renderApp(<Routes><Route path="/legal/:doc" element={<LegalPage />} /></Routes>, { route: `/legal/${doc}`, withAuth: false })

describe('legal pages', () => {
  it.each(['privacy', 'terms', 'security', 'license'])('%s renders as a public page with contents; the draft notice and highlighted marks show only while details are unfilled', (doc) => {
    page(doc)
    expect(screen.getByRole('heading', { level: 1, name: DOCS[doc].title })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Contents' })
    expect(within(nav).getAllByRole('link')).toHaveLength(DOCS[doc].sections.length)
    if (hasUnfilled(DOCS[doc])) {
      expect(screen.getByRole('alert')).toHaveTextContent(/lawyer/i)
      expect(document.querySelectorAll('mark').length).toBeGreaterThan(0)                  // unfilled details are visibly marked, never presented as real values
    } else {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      expect(document.querySelectorAll('mark')).toHaveLength(0)
    }
    expect(document.body.textContent).not.toMatch(/\[\[/)                                    // raw markup never leaks into the page
    expect(document.body.textContent).not.toMatch(/\{\{/)                                    // every {{key}} has a value in operator.json
  })

  it('fillOperator replaces known {{keys}} and leaves unknown ones visible', () => {
    expect(fillOperator('Copyright {{year}}')).toMatch(/^Copyright \S+/)
    expect(fillOperator('{{doesNotExist}}')).toBe('{{doesNotExist}}')
    expect(hasUnfilled({ effective: '', sections: [{ blocks: [{ p: 'plain text' }] }] })).toBe(false)
    expect(hasUnfilled({ effective: '', sections: [{ blocks: [{ p: 'see [[something missing]]' }] }] })).toBe(true)
  })

  it('the privacy policy states the OpenAI and Pinecone disclosures prominently', () => {
  page('privacy')
  const notes = screen.getAllByRole('note')
  expect(notes.some((n) => /sends parts of your source code to OpenAI/i.test(n.textContent))).toBe(true)
  expect(screen.getByRole('heading', { name: /your code is sent to third parties/i })).toBeInTheDocument()
  expect(screen.getAllByText(/Pinecone/).length).toBeGreaterThan(2)
  })

  it('shows tables as real tables and unknown documents as not found', () => {
    page('privacy')
    expect(screen.getAllByRole('table').length).toBeGreaterThan(2)
    expect(screen.getAllByRole('columnheader').length).toBeGreaterThan(8)
  })

  it('does not render unknown or prototype-polluting document names', () => {
    page('constructor')
    expect(screen.queryByRole('article')).not.toBeInTheDocument()
    expect(screen.getByText(/not found|404/i)).toBeInTheDocument()
  })
})

describe('legal footer', () => {
  it('links to all four documents', () => {
    renderApp(<LegalFooter />, { withAuth: false })
    const nav = screen.getByRole('navigation', { name: 'Legal' })
    for (const [to, label] of LEGAL_LINKS) expect(within(nav).getByRole('link', { name: label })).toHaveAttribute('href', to)
    expect(LEGAL_LINKS.map(([to]) => to)).toEqual(['/legal/privacy', '/legal/terms', '/legal/security', '/legal/license'])
  })
})