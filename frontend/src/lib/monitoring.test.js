import { describe, expect, it } from 'vitest'
import { scrubBreadcrumb, scrubEvent } from './monitoring'

const FAKE_TOKEN = `ghp_${'a1b2'.repeat(9)}` // built at runtime so repository secret scanners do not flag the file

describe('monitoring scrubbing', () => {
  it('removes everything that could carry secrets or code before an event leaves the browser', () => {
    const ev = scrubEvent({
      request: { method: 'GET', url: 'https://app.example/auth/callback?code=OAUTHCODE&state=S', headers: { Cookie: 'x' }, cookies: { a: 'b' } },
      user: { id: 7, email: 'a@b.c', ip_address: '1.2.3.4' },
      exception: { values: [{ value: `failed ${FAKE_TOKEN} Bearer abc.def`, stacktrace: { frames: [{ filename: 'a.js', vars: { token: 'x' }, context_line: 'SECRET' }] } }] },
      extra: { apiToken: 't', count: 3 },
      breadcrumbs: [{ category: 'console', message: 'dbg' }, { category: 'fetch', message: 'm', data: { url: '/api/x?token=1', method: 'GET', status_code: 500, body: 'SECRETBODY' } }],
    })
    const blob = JSON.stringify(ev)
    for (const leak of ['OAUTHCODE', 'Cookie', 'a@b.c', '1.2.3.4', FAKE_TOKEN, 'Bearer abc', 'SECRET', 'token=1', 'dbg']) expect(blob).not.toContain(leak)
    expect(ev.request).toEqual({ method: 'GET', url: 'https://app.example/auth/callback' })
    expect(ev.user).toEqual({ id: '7' })
    expect(ev.extra.apiToken).toBe('[Filtered]')
    expect(ev.breadcrumbs).toHaveLength(1)
    expect(ev.breadcrumbs[0].data).toEqual({ method: 'GET', status_code: 500, url: '/api/x' })
  })
  it('drops console breadcrumbs and tolerates null', () => {
    expect(scrubBreadcrumb({ category: 'console' })).toBeNull()
    expect(scrubEvent(null)).toBeNull()
  })
})
