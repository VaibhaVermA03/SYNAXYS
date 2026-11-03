import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setCsrfToken } from './api'
import { mockFetch } from '../test/utils'

afterEach(() => { setCsrfToken(null); vi.unstubAllGlobals() })

describe('api client', () => {
  it('sends cookies and no CSRF header on GET', async () => {
    const f = mockFetch(() => ({ body: { ok: 1 } }))
    setCsrfToken('tok')
    await api('/x', { params: { a: 1, b: '' } })
    const [url, init] = f.mock.calls[0]
    expect(url).toBe('/api/v1/x?a=1')
    expect(init.credentials).toBe('include')
    expect(init.headers['X-CSRF-Token']).toBeUndefined()
  })

  it('adds the CSRF header on unsafe methods once known', async () => {
    const f = mockFetch(() => ({ status: 204 }))
    await api('/x', { method: 'POST' })
    expect(f.mock.calls[0][1].headers['X-CSRF-Token']).toBeUndefined()
    setCsrfToken('tok')
    expect(await api('/x', { method: 'DELETE' })).toBeNull()
    expect(f.mock.calls[1][1].headers['X-CSRF-Token']).toBe('tok')
  })

  it('maps the error envelope to ApiError', async () => {
    mockFetch(() => ({ status: 409, body: { error: { code: 'github_reauth_required', message: 'Sign in again' } } }))
    await expect(api('/x')).rejects.toMatchObject({ status: 409, code: 'github_reauth_required', message: 'Sign in again' })
  })

  it('reports network failures distinctly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('failed')))
    await expect(api('/x')).rejects.toMatchObject({ code: 'network_error', status: 0 })
  })

  it('announces 401s so the app can end the session', async () => {
    mockFetch(() => ({ status: 401, body: { error: { code: 'unauthorized', message: 'no' } } }))
    const spy = vi.fn(); window.addEventListener('synaxys:unauthorized', spy)
    await expect(api('/x')).rejects.toBeInstanceOf(ApiError)
    expect(spy).toHaveBeenCalled(); window.removeEventListener('synaxys:unauthorized', spy)
  })
})

describe('csrf recovery', () => {
  it('announces a rejected CSRF token so the app can refresh its session state', async () => {
    mockFetch(() => ({ status: 403, body: { error: { code: 'csrf_failed', message: 'Missing or invalid CSRF token' } } }))
    const spy = vi.fn(); window.addEventListener('synaxys:csrf-failed', spy)
    await expect(api('/x', { method: 'POST' })).rejects.toMatchObject({ status: 403, code: 'csrf_failed' })
    expect(spy).toHaveBeenCalled(); window.removeEventListener('synaxys:csrf-failed', spy)
  })
  it('does not treat ordinary 403s as CSRF failures', async () => {
    mockFetch(() => ({ status: 403, body: { error: { code: 'forbidden', message: 'nope' } } }))
    const spy = vi.fn(); window.addEventListener('synaxys:csrf-failed', spy)
    await expect(api('/x', { method: 'POST' })).rejects.toBeInstanceOf(ApiError)
    expect(spy).not.toHaveBeenCalled(); window.removeEventListener('synaxys:csrf-failed', spy)
  })
})
