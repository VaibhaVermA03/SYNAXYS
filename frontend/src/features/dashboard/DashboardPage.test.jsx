import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import DashboardPage from './DashboardPage'
import { mockFetch, renderApp } from '../../test/utils'

afterEach(() => vi.unstubAllGlobals())
const days = Array.from({ length: 14 }, (_, i) => ({ date: `2026-01-${String(i + 1).padStart(2, '0')}`, count: i === 13 ? 3 : 0 }))
const dash = (o = {}) => ({ total_repositories: 2, connected_repositories: 1, open_pull_requests: 4, reviews_completed: 5, reviews_by_status: { completed: 5, failed: 1 }, findings_by_severity: { critical: 0, high: 2, medium: 1, low: 0, info: 0 },
  avg_review_duration_ms: 4200, indexing_by_status: { indexed: 1, failed: 1 }, recent_reviews: [], has_demo_data: false, reviews_by_day: days, published_comments: 7, failed_reviews: 1, ...o })

describe('DashboardPage', () => {
  it('shows usage metrics, an accessible 14-day chart and index summary', async () => {
    mockFetch(() => ({ body: dash() })); renderApp(<DashboardPage />, { withAuth: false })
    expect(await screen.findByText('Comments published')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /reviews per day over the last 14 days.*2026-01-14: 3/i })).toBeInTheDocument()
    expect(screen.getByText(/1 indexed · 1 failed/)).toBeInTheDocument()
    expect(screen.getByText(/open code reviews to retry/i)).toBeInTheDocument()
  })
  it('shows a first-run empty state and an error state with retry', async () => {
    mockFetch(() => ({ body: dash({ total_repositories: 0 }) })); renderApp(<DashboardPage />, { withAuth: false })
    expect(await screen.findByText(/connect your first repository/i)).toBeInTheDocument()
    vi.unstubAllGlobals()
    mockFetch(() => ({ status: 500, body: { error: { code: 'internal_error', message: 'x' } } })); renderApp(<DashboardPage />, { withAuth: false })
    expect(await screen.findByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})
