// Fetch-based API client. Auth is a HttpOnly session cookie (never stored in JS);
// unsafe requests also carry the CSRF token obtained from /auth/me (kept in memory only).
const BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
let csrfToken = null

export const setCsrfToken = (t) => { csrfToken = t }

export class ApiError extends Error {
  constructor(status, code, message, fields) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fields = fields
  }
}

function buildUrl(path, params) {
  const qs = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') qs.set(k, String(v)) })
  const s = qs.toString()
  return `${BASE}${path}${s ? `?${s}` : ''}`
}

export async function api(path, { method = 'GET', body, params, signal } = {}) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (UNSAFE.has(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken
  let res
  try {
    res = await fetch(buildUrl(path, params), { method, headers, credentials: 'include', signal, body: body !== undefined ? JSON.stringify(body) : undefined })
  } catch (e) {
    if (e?.name === 'AbortError') throw e
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check your connection and try again.')
  }
  if (res.status === 204) return null
  let data = null
  try { data = await res.json() } catch { /* non-JSON body */ }
  if (!res.ok) {
    const err = data?.error
    if (res.status === 401) window.dispatchEvent(new Event('synaxys:unauthorized'))
    if (res.status === 403 && err?.code === 'csrf_failed') window.dispatchEvent(new Event('synaxys:csrf-failed'))
    throw new ApiError(res.status, err?.code || 'http_error', err?.message || `Request failed (${res.status})`, err?.fields)
  }
  return data
}

export function describeError(e) {
  if (!(e instanceof ApiError)) return 'Something went wrong.'
  if (e.status === 429) return 'Too many requests. Please wait a moment and try again.'
  if (e.status === 403) return e.message || 'You do not have permission to do that.'
  if (e.status >= 500) return 'The server had a problem. Please try again shortly.'
  return e.message
}
