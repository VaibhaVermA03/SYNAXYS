import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './routes/ProtectedRoute'
import AppLayout from './components/layout/AppLayout'
import LoginPage from './features/auth/LoginPage'
import AuthCallbackPage from './features/auth/AuthCallbackPage'
import DashboardPage from './features/dashboard/DashboardPage'
import RepositoriesPage from './features/repositories/RepositoriesPage'
import PullRequestsPage from './features/pull-requests/PullRequestsPage'
import PullRequestDetailPage from './features/pull-requests/PullRequestDetailPage'
import ReviewsPage from './features/reviews/ReviewsPage'
import ReviewDetailPage from './features/reviews/ReviewDetailPage'
import CodeSearchPage from './features/code-search/CodeSearchPage'
import RulesPage from './features/rules/RulesPage'
import SettingsPage from './features/settings/SettingsPage'
import IntegrationsPage from './features/settings/IntegrationsPage'

import NotFoundPage from './pages/NotFoundPage'

const NotFoundStandalone = () => <div className="mx-auto max-w-xl p-6"><NotFoundPage /></div>

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/auth/callback" element={<AuthCallbackPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/app" element={<AppLayout />}>
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="repositories" element={<RepositoriesPage />} />
          <Route path="pull-requests" element={<PullRequestsPage />} />
          <Route path="pull-requests/:pullRequestId" element={<PullRequestDetailPage />} />
          <Route path="reviews" element={<ReviewsPage />} />
          <Route path="reviews/:reviewId" element={<ReviewDetailPage />} />
          <Route path="code-search" element={<CodeSearchPage />} />
          <Route path="rules" element={<RulesPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="settings/integrations" element={<IntegrationsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
      <Route path="/" element={<Navigate to="/app/dashboard" replace />} />
      <Route path="*" element={<NotFoundStandalone />} />
    </Routes>
  )
}
