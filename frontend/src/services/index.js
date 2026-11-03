import { api } from '../lib/api'

export const authService = {
  config: () => api('/auth/config'),
  me: () => api('/auth/me'),
  logout: () => api('/auth/logout', { method: 'POST' }),
}

export const githubService = {
  repositories: (params) => api('/github/repositories', { params }),
  installations: () => api('/github/installations'),
  sync: () => api('/github/repositories/sync', { method: 'POST' }),
  connect: (id) => api(`/github/repositories/${id}/connect`, { method: 'POST' }),
  disconnect: (id) => api(`/github/repositories/${id}/disconnect`, { method: 'DELETE' }),
  revokeCredentials: () => api('/github/credentials', { method: 'DELETE' }),
}

export const dashboardService = { get: () => api('/dashboard') }

export const pullRequestService = {
  list: (params) => api('/pull-requests', { params }),
  get: (id) => api(`/pull-requests/${id}`),
  diff: (id) => api(`/pull-requests/${id}/diff`),
  requestReview: (id) => api(`/pull-requests/${id}/review`, { method: 'POST' }),
}

export const reviewService = {
  list: (params) => api('/reviews', { params }),
  get: (id) => api(`/reviews/${id}`),
  retry: (id) => api(`/reviews/${id}/retry`, { method: 'POST' }),
  approve: (id, commentIds) => api(`/reviews/${id}/approve`, { method: 'POST', body: { comment_ids: commentIds ?? null } }),
  publish: (id) => api(`/reviews/${id}/publish`, { method: 'POST' }),
  updateComment: (id, commentId, body) => api(`/reviews/${id}/comments/${commentId}`, { method: 'PATCH', body }),
  attempts: (id) => api(`/reviews/${id}/posting-attempts`),
}

export const ruleService = {
  list: (params) => api('/review-rules', { params }),
  create: (body) => api('/review-rules', { method: 'POST', body }),
  update: (id, body) => api(`/review-rules/${id}`, { method: 'PATCH', body }),
  remove: (id) => api(`/review-rules/${id}`, { method: 'DELETE' }),
  test: (body) => api('/review-rules/test', { method: 'POST', body }),
}

export const repoConfigService = {
  get: (id) => api(`/github/repositories/${id}/config`),
  update: (id, body) => api(`/github/repositories/${id}/config`, { method: 'PATCH', body }),
}

export const indexService = {
  status: (id) => api(`/repositories/${id}/index-status`),
  start: (id) => api(`/repositories/${id}/index`, { method: 'POST' }),
}

export const searchService = { query: (body) => api('/code-search/query', { method: 'POST', body }) }

export const settingsService = {
  integrations: () => api('/settings/integrations'),
  audit: (limit = 50) => api('/settings/audit', { params: { limit } }),
}
