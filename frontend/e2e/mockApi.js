// Stateful in-browser fake of the SYNAXYS API for Playwright (page.route). Shapes mirror the real backend.
export const ME = { user: { id: 1, login: 'alice', name: 'Alice', avatar_url: null }, csrf_token: 'csrf-e2e',
  integrations: { github_oauth: true, github_app: true, webhook_secret: true, openai: true, pinecone: true, demo_mode: false, demo_login: false } }

const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
const err = (route, status, code, message) => json(route, { error: { code, message } }, status)

export function makeState() {
  return {
    signedIn: false, calls: [],
    repo: { id: 1, full_name: 'alice/shop', default_branch: 'main', is_private: true, language: 'Python', html_url: null, is_enabled: false, is_demo: false, role: 'owner', index_status: 'not_indexed', last_indexed_at: null, index_error: null },
    review: null, comment: { id: 11, state: 'draft', body: 'Possible SQL injection: use parameterized queries.', edited: false }, published: false,
  }
}

const finding = (st) => ({ id: 21, category: 'security', severity: 'high', title: 'SQL injection via string concatenation', explanation: 'User input is concatenated into SQL.', evidence: 'cur.execute(q)',
  path: 'app/users.py', start_line: 12, end_line: 12, remediation: 'Use a parameterized query.', patch: null, confidence: 0.9, confidence_label: 'high', inline_possible: true, status: st.published ? 'published' : 'open', comment: st.comment })
const brief = (st) => (st.review ? { id: 3, status: st.review, trigger: 'manual', findings: st.review === 'completed' ? 1 : 0, by_severity: { critical: 0, high: st.review === 'completed' ? 1 : 0, medium: 0, low: 0, info: 0 }, created_at: '2026-01-01T00:00:00Z', head_sha: 'a'.repeat(40), is_demo: false } : null)
const pr = (st) => ({ id: 9, repository_id: 1, repository: 'alice/shop', number: 7, title: 'Add user lookup', author: 'bob', state: 'open', base_branch: 'main', head_branch: 'feat/lookup', html_url: 'https://github.com/alice/shop/pull/7', updated_at: '2026-01-01T00:00:00Z', is_demo: false, review: brief(st) })
const DIFF = { files: [{ path: 'app/users.py', previous_path: null, status: 'modified', additions: 2, deletions: 0, skipped_reason: null, hunks: [{ header: '@@ -10,2 +10,4 @@', lines: [
  { kind: 'context', old_no: 10, new_no: 10, text: 'cur = db.cursor()' }, { kind: 'add', old_no: null, new_no: 11, text: "q = \"SELECT * FROM u WHERE n='\" + n" }, { kind: 'add', old_no: null, new_no: 12, text: 'cur.execute(q)' }] }] }], omitted_files: 0, head_sha: 'a'.repeat(40), is_demo: false }
const reviewDetail = (st) => ({ ...brief(st), repository: 'alice/shop', pr_id: 9, pr_number: 7, pr_title: 'Add user lookup', summary: 'AI-assisted review by mock: 1 suggestion.', model: 'mock-llm (deterministic keyword matcher, not AI)', ai_generated: true,
  by_category: { security: 1 }, findings_list: st.review === 'completed' ? [finding(st)] : [], require_approval: true, auto_publish: false, can_retry: false, can_manage: true,
  approved_comments: st.comment.state === 'approved' ? 1 : 0, publishable: st.comment.state === 'approved' && !st.published, publish_blocker: null })

export async function installMockApi(page, st = makeState()) {
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request(); const url = new URL(req.url()); const path = url.pathname.replace('/api/v1', ''); const m = req.method()
    st.calls.push(`${m} ${path}`)
    const unsafe = m !== 'GET'
    if (path === '/auth/config') return json(route, ME.integrations)
    // the real OAuth round-trip is faked: the login link hits this route, which "signs in" and redirects to the frontend callback page like the real backend does
    if (path === '/auth/github/login') { st.signedIn = true; return route.fulfill({ status: 302, headers: { location: '/auth/callback?status=success' } }) }
    if (path === '/auth/me') return st.signedIn ? json(route, ME) : err(route, 401, 'unauthorized', 'Authentication required')
    if (!st.signedIn) return err(route, 401, 'unauthorized', 'Authentication required')
    if (unsafe && req.headers()['x-csrf-token'] !== 'csrf-e2e') return err(route, 403, 'csrf_failed', 'Missing or invalid CSRF token')
    if (path === '/auth/logout') { st.signedIn = false; return route.fulfill({ status: 204 }) }
    if (path === '/dashboard') return json(route, { total_repositories: 1, connected_repositories: st.repo.is_enabled ? 1 : 0, open_pull_requests: 1, reviews_completed: st.review === 'completed' ? 1 : 0, reviews_by_status: st.review ? { [st.review]: 1 } : {},
      findings_by_severity: { critical: 0, high: st.review === 'completed' ? 1 : 0, medium: 0, low: 0, info: 0 }, avg_review_duration_ms: null, indexing_by_status: { [st.repo.index_status]: 1 }, recent_reviews: [], has_demo_data: false,
      reviews_by_day: Array.from({ length: 14 }, (_, i) => ({ date: `2026-01-${String(i + 1).padStart(2, '0')}`, count: 0 })), published_comments: st.published ? 1 : 0, failed_reviews: 0 })
    if (path === '/github/installations') return json(route, { items: [], install_url: null })
    if (path === '/github/repositories') return json(route, { items: [st.repo], total: 1, page: 1, page_size: 20 })
    if (path === '/github/repositories/1/connect') { st.repo.is_enabled = true; return json(route, st.repo) }
    if (path === '/repositories/1/index') { st.repo.index_status = 'indexed'; st.repo.last_indexed_at = '2026-01-01T00:00:00Z'; return json(route, { status: 'indexed', available: true, backend: 'pinecone', indexed_files: 3, job: null }, 202) }
    if (path === '/repositories/1/index-status') return json(route, { status: st.repo.index_status, available: true, backend: 'pinecone', indexed_files: 3, job: null })
    if (path === '/pull-requests') return json(route, { items: [pr(st)], total: 1, page: 1, page_size: 20 })
    if (path === '/pull-requests/9') return json(route, { ...pr(st), head_sha: 'a'.repeat(40), repo_enabled: st.repo.is_enabled, can_request_review: st.repo.is_enabled, reviews: st.review ? [brief(st)] : [] })
    if (path === '/pull-requests/9/diff') return json(route, DIFF)
    if (path === '/pull-requests/9/review') { st.review = 'completed'; return json(route, brief(st), 202) }   // the mocked AI finishes instantly
    if (path === '/reviews') return json(route, { items: st.review ? [{ ...brief(st), repository: 'alice/shop', pr_id: 9, pr_number: 7, pr_title: 'Add user lookup' }] : [], total: st.review ? 1 : 0, page: 1, page_size: 20 })
    if (path === '/reviews/3') return json(route, reviewDetail(st))
    if (path === '/reviews/3/posting-attempts') return json(route, st.published ? [{ id: 1, comment_id: 11, status: 'success', http_status: 200, error: null, actor: 'alice', created_at: '2026-01-01T00:00:00Z' }] : [])
    if (path === '/reviews/3/approve') { st.comment.state = 'approved'; return json(route, { approved: 1 }) }
    if (path === '/reviews/3/publish') { st.comment.state = 'published'; st.published = true; return json(route, { posted: 1, skipped_existing: 0, failed: 0, github_review_id: 77 }) }
    if (path === '/code-search/query') return json(route, { results: [{ id: 'a#0001', score: 0.82, repository: 'alice/shop', repository_id: 1, path: 'app/db.py', start_line: 3, end_line: 9, language: 'python', branch: 'main', commit: 'abc',
      snippet: 'def open_connection(pool):\n    return pool.acquire()', explanation: 'strong semantic similarity (0.82); code mentions pool', github_url: 'https://github.com/alice/shop/blob/abc/app/db.py#L3-L9' }], searched_repositories: ['alice/shop'], backend: 'Pinecone', note: null })
    if (path === '/review-rules') return json(route, [])
    return err(route, 404, 'not_found', `e2e mock has no route for ${m} ${path}`)
  })
  return st
}
