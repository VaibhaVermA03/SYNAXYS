import { useQuery } from '@tanstack/react-query'
import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { Github, KeyRound } from 'lucide-react'
import Logo from '../../components/layout/Logo'
import ThemeToggle from '../../components/layout/ThemeToggle'
import { ErrorState, Skeleton } from '../../components/ui'
import AmbientBackground from './AmbientBackground'
import LoginShowcase from './LoginShowcase'
import { useAuth } from '../../app/AuthProvider'
import { describeError } from '../../lib/api'
import { authService } from '../../services'

export const LOGIN_ERRORS = {
  access_denied: 'GitHub sign-in was cancelled. You can try again whenever you are ready.',
  invalid_state: 'The sign-in attempt expired or could not be verified. Please try again.',
  oauth_failed: 'GitHub sign-in failed. Please try again; if it keeps failing, contact your administrator.',
  not_configured: 'GitHub sign-in is not configured on this server.',
}

function ConfigNotice() {
  return (
    <div role="alert" className="rounded-lg border border-warn/40 bg-warn/10 p-4 text-left text-sm">
      <div className="flex items-center gap-2 font-semibold"><KeyRound className="h-4 w-4" aria-hidden />GitHub sign-in is not configured</div>
      <p className="mt-2 text-muted">Set <code>GITHUB_CLIENT_ID</code> and <code>GITHUB_CLIENT_SECRET</code> in <code>backend/.env</code>, then restart the backend. See the GitHub OAuth setup guide in the README.</p>
    </div>
  )
}

export default function LoginPage() {
  const { status } = useAuth()
  const [params] = useSearchParams()
  const location = useLocation()
  const config = useQuery({ queryKey: ['auth-config'], queryFn: authService.config, retry: 1 })

  if (status === 'authenticated') return <Navigate to={location.state?.from || '/app/dashboard'} replace />
  const urlError = LOGIN_ERRORS[params.get('error')]

  return (
    <div className="relative h-screen h-dvh overflow-hidden lg:grid lg:grid-cols-2 lg:grid-rows-[minmax(0,1fr)]">
      {/* mobile: only a background effect; desktop: the showcase column on the right */}
      <AmbientBackground className="lg:hidden" />
      <div className="absolute right-3 top-3 z-20 sm:right-4 sm:top-4"><ThemeToggle align="end" /></div>

      <main className="relative z-10 flex h-full min-h-0 overflow-y-auto p-5 sm:p-8">
        <div className="m-auto w-full max-w-sm rounded-2xl border border-border bg-surface/80 p-7 text-center shadow-lg backdrop-blur-md lg:border-0 lg:bg-transparent lg:p-0 lg:text-left lg:shadow-none lg:backdrop-blur-none">
          <div className="mb-8 flex justify-center lg:justify-start"><Logo size="lg" /></div>
          <h1 className="text-2xl">Sign in</h1>
          <p className="mt-1 text-sm text-muted lg:hidden">Smarter Reviews. Safer Code.</p>
          <p className="mt-2 text-sm text-muted">Use your GitHub account to review pull requests and search your codebase.</p>
          <div className="mt-6 space-y-3">
            {urlError && <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">{urlError}</p>}
            {config.isPending && <Skeleton className="h-10 w-full" />}
            {config.isError && <ErrorState message={describeError(config.error)} onRetry={config.refetch} />}
            {config.data && !config.data.github_oauth && <ConfigNotice />}
            {config.data?.github_oauth && (
              // Plain navigation: the server runs the OAuth redirect (state + PKCE) itself.
              <a href="/api/v1/auth/github/login" className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-fg px-4 py-2.5 text-sm font-medium text-bg hover:opacity-90">
                <Github className="h-4 w-4" strokeWidth={1.5} aria-hidden />Continue with GitHub
              </a>
            )}
          </div>
        </div>
      </main>

      <LoginShowcase />
    </div>
  )
}
