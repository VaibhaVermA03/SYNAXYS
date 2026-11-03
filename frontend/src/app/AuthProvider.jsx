import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useToast } from '../components/ui/Toast'
import { ApiError, describeError, setCsrfToken } from '../lib/api'
import { authService } from '../services'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { toast } = useToast()
  const [signedOut, setSignedOut] = useState(false)
  const q = useQuery({
    queryKey: ['me'],
    queryFn: async () => { const me = await authService.me(); setCsrfToken(me.csrf_token); return me },
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  // Forget the session locally. NEVER use qc.clear() here: it destroys the cached ['me'] query that this component's
  // useQuery is subscribed to, so the new data written by setQueryData reaches nobody and the UI keeps showing "signed in".
  const dropSession = useCallback(() => {
    setCsrfToken(null)
    qc.setQueryData(['me'], null) // notifies the mounted observer
    qc.removeQueries({ predicate: (x) => x.queryKey[0] !== 'me' && x.queryKey[0] !== 'auth-config' })
  }, [qc])

  // A new successful /auth/me (after logging in again) ends the signed-out state.
  useEffect(() => { if (q.data) setSignedOut(false) }, [q.data])

  // Any 401 from the API means the session ended: drop cached data and show login.
  useEffect(() => {
    const onUnauthorized = () => { setSignedOut(true); dropSession() }
    window.addEventListener('synaxys:unauthorized', onUnauthorized)
    return () => window.removeEventListener('synaxys:unauthorized', onUnauthorized)
  }, [dropSession])

  // A rejected CSRF token usually means the page outlived its session state: re-fetch /auth/me (new token, or 401 -> login).
  useEffect(() => {
    const onCsrf = () => { qc.invalidateQueries({ queryKey: ['me'] }) }
    window.addEventListener('synaxys:csrf-failed', onCsrf)
    return () => window.removeEventListener('synaxys:csrf-failed', onCsrf)
  }, [qc])

  const logout = useCallback(async () => {
    try {
      await authService.logout()
    } catch (e) {
      // 401 = the session was already gone, so signing out locally is correct. Any other failure means the server
      // session may still be alive: stay signed in and say so instead of pretending to sign out.
      if (!(e instanceof ApiError && e.status === 401)) {
        toast(`Sign out failed: ${describeError(e)}`, 'error')
        return false
      }
    }
    setSignedOut(true)
    dropSession()
    navigate('/login', { replace: true })
    return true
  }, [dropSession, navigate, toast])

  const value = useMemo(() => {
    const unauth = q.error instanceof ApiError && q.error.status === 401
    const status = signedOut ? 'unauthenticated' : q.isPending ? 'loading' : q.data ? 'authenticated' : unauth || q.data === null ? 'unauthenticated' : 'error'
    return { status, user: q.data?.user ?? null, integrations: q.data?.integrations ?? null, error: q.error, refetch: q.refetch, logout }
  }, [signedOut, q.isPending, q.data, q.error, q.refetch, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}