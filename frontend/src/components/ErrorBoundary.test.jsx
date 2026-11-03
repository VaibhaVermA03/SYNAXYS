import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ErrorBoundary from './ErrorBoundary'
import NotFoundPage from '../pages/NotFoundPage'

afterEach(() => vi.restoreAllMocks())
const Boom = () => { throw new Error('render crash') }

describe('ErrorBoundary / NotFound', () => {
  it('replaces a crashed tree with a recoverable message instead of a blank page', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<ErrorBoundary><Boom /></ErrorBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent(/something went wrong/i)
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument()
  })
  it('renders children normally', () => { render(<ErrorBoundary><p>fine</p></ErrorBoundary>); expect(screen.getByText('fine')).toBeInTheDocument() })
  it('has a helpful not-found page', () => {
    render(<MemoryRouter initialEntries={['/nope']}><Routes><Route path="*" element={<NotFoundPage />} /></Routes></MemoryRouter>)
    expect(screen.getByText(/page not found/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to the dashboard/i })).toHaveAttribute('href', '/app/dashboard')
  })
})
