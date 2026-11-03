import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../app/AuthProvider'
import { ErrorState, Skeleton } from '../components/ui'
import { describeError } from '../lib/api'

// UX guard only: the backend enforces authorization on every API call.
export default function ProtectedRoute() {
  const { status, error, refetch } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <div className="p-8"><Skeleton className="h-8 w-48" /><Skeleton className="mt-4 h-64 w-full" /></div>
  if (status === 'error') return <ErrorState message={describeError(error)} onRetry={refetch} />
  if (status === 'unauthenticated') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}
