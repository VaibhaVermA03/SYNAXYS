import { useEffect } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Skeleton } from '../../components/ui'
import { useAuth } from '../../app/AuthProvider'
import { LOGIN_ERRORS } from './LoginPage'

// The backend has already validated state/PKCE and set the session cookie before redirecting here.
export default function AuthCallbackPage() {
  const [params] = useSearchParams()
  const qc = useQueryClient()
  const { status } = useAuth()
  const error = params.get('error')
  const ok = params.get('status') === 'success'

  useEffect(() => { if (ok) qc.invalidateQueries({ queryKey: ['me'] }) }, [ok, qc])

  if (error || !ok) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <div role="alert" className="max-w-md text-center">
          <h1 className="text-lg font-semibold">Sign-in failed</h1>
          <p className="mt-2 text-sm text-muted">{LOGIN_ERRORS[error] || 'Sign-in could not be completed.'}</p>
          <Link to="/login" className="mt-4 inline-block text-sm font-medium text-accent-ink underline">Back to sign in</Link>
        </div>
      </div>
    )
  }
  if (status === 'authenticated') return <Navigate to="/app/dashboard" replace />
  if (status === 'unauthenticated') return <Navigate to="/login?error=oauth_failed" replace />
  return <div className="p-8"><Skeleton className="h-8 w-48" /></div>
}
