// Browser error tracking (Sentry). Entirely optional: with no VITE_SENTRY_DSN nothing is loaded or sent.
// What is never sent: request bodies, cookies, headers, query strings, user details, local variables, replays.
// (The DSN is a public identifier by design; it is not a secret.)
const SENSITIVE = /(authorization|cookie|token|secret|password|csrf|session|code|state|key)/i
const TOKEN_LIKE = /(gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*|Bearer\s+\S+)/g

const strip = (u) => (typeof u === 'string' ? u.split('?')[0].split('#')[0] : u)
const clean = (s) => (typeof s === 'string' ? s.replace(TOKEN_LIKE, '[redacted]').slice(0, 500) : s)

export function scrubEvent(event) {
  if (!event) return null
  if (event.request) event.request = { method: event.request.method, url: strip(event.request.url) }
  event.user = event.user?.id ? { id: String(event.user.id) } : undefined
  for (const v of event.exception?.values ?? []) {
    if (v.value) v.value = clean(v.value)
    for (const f of v.stacktrace?.frames ?? []) { delete f.vars; delete f.pre_context; delete f.context_line; delete f.post_context }
  }
  if (typeof event.message === 'string') event.message = clean(event.message)
  for (const k of ['extra', 'contexts', 'tags']) {
    if (event[k]) for (const key of Object.keys(event[k])) if (SENSITIVE.test(key)) event[k][key] = '[Filtered]'
  }
  if (event.breadcrumbs) event.breadcrumbs = event.breadcrumbs.map(scrubBreadcrumb).filter(Boolean)
  return event
}

export function scrubBreadcrumb(b) {
  if (!b || b.category === 'console') return null
  const data = {}
  if (b.data) for (const k of ['method', 'status_code']) if (b.data[k] !== undefined) data[k] = b.data[k]
  if (b.data?.url) data.url = strip(b.data.url)
  return { ...b, message: clean(b.message), data }
}

let sentry = null

export async function initMonitoring() {
  const dsn = import.meta.env.VITE_SENTRY_DSN
  if (!dsn) return false
  try {
    const S = await import('@sentry/react')
    S.init({
      dsn,
      environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || import.meta.env.MODE,
      release: import.meta.env.VITE_APP_RELEASE || undefined,
      sendDefaultPii: false,
      tracesSampleRate: 0,
      defaultIntegrations: false, // only the integrations below: no console/DOM/fetch breadcrumbs with URLs or text
      integrations: [S.globalHandlersIntegration(), S.linkedErrorsIntegration(), S.dedupeIntegration(), S.functionToStringIntegration(), S.inboundFiltersIntegration()],
      beforeSend: scrubEvent,
      beforeBreadcrumb: scrubBreadcrumb,
      ignoreErrors: ['ResizeObserver loop limit exceeded', 'ResizeObserver loop completed with undelivered notifications.'],
    })
    sentry = S
    return true
  } catch {
    return false // monitoring must never break the app
  }
}

export function captureError(error, context) {
  try {
    if (sentry) sentry.captureException(error, context ? { extra: { componentStack: String(context).slice(0, 2000) } } : undefined)
  } catch { /* ignore */ }
}
