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
  get: (id, params) => api(`/reviews/${id}`, { params }),
  retry: (id) => api(`/reviews/${id}/retry`, { method: 'POST' }),
  approve: (id, commentIds) => api(`/reviews/${id}/approve`, { method: 'POST', body: { comment_ids: commentIds ?? null } }),
  publish: (id) => api(`/reviews/${id}/publish`, { method: 'POST' }),
  updateComment: (id, commentId, body) => api(`/reviews/${id}/comments/${commentId}`, { method: 'PATCH', body }),
  attempts: (id) => api(`/reviews/${id}/posting-attempts`),
  dismissFinding: (id, findingId, body) => api(`/reviews/${id}/findings/${findingId}/dismiss`, { method: 'POST', body: body ?? {} }),
  restoreFinding: (id, findingId) => api(`/reviews/${id}/findings/${findingId}/restore`, { method: 'POST' }),
  cancel: (id) => api(`/reviews/${id}/cancel`, { method: 'POST' }),
  deleteGithubComment: (id, commentId) => api(`/reviews/${id}/comments/${commentId}/github`, { method: 'DELETE' }),
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
  status: (id, branch) => api(`/repositories/${id}/index-status`, { params: branch ? { branch } : undefined }),
  start: (id, branch) => api(`/repositories/${id}/index`, { method: 'POST', body: branch ? { branch } : undefined }),
  retryFailed: (id, branch) => api(`/repositories/${id}/index/retry-failed`, { method: 'POST', body: branch ? { branch } : undefined }),
  githubBranches: (id) => api(`/repositories/${id}/github-branches`),
  removeBranch: (id, branch) => api(`/repositories/${id}/branches/${encodeURIComponent(branch).replace(/%2F/g, '/')}`, { method: 'DELETE' }),
}

export const searchService = {
  query: (body) => api('/code-search/query', { method: 'POST', body }),
  branches: (params) => api('/code-search/branches', { params }),
}

export const settingsService = {
  integrations: () => api('/settings/integrations'),
  audit: (limit = 50) => api('/settings/audit', { params: { limit } }),
}

export const adminService = {
  jobs: (params) => api('/admin/jobs', { params }),
  summary: () => api('/admin/jobs/summary'),
  job: (id) => api(`/admin/jobs/${id}`),
  retry: (id) => api(`/admin/jobs/${id}/retry`, { method: 'POST' }),
}

export const workspaceService = {
  list: () => api('/workspaces'),
  create: (name) => api('/workspaces', { method: 'POST', body: { name } }),
  update: (id, body) => api(`/workspaces/${id}`, { method: 'PATCH', body }),
  remove: (id, confirm_name) => api(`/workspaces/${id}/delete`, { method: 'POST', body: { confirm_name } }),
  members: (id) => api(`/workspaces/${id}/members`, { workspaceId: id }),
  setRole: (id, userId, role) => api(`/workspaces/${id}/members/${userId}`, { method: 'PATCH', body: { role } }),
  removeMember: (id, userId) => api(`/workspaces/${id}/members/${userId}`, { method: 'DELETE' }),
  leave: (id) => api(`/workspaces/${id}/leave`, { method: 'POST' }),
  transfer: (id, user_id) => api(`/workspaces/${id}/transfer`, { method: 'POST', body: { user_id } }),
  invitations: (id) => api(`/workspaces/${id}/invitations`),
  invite: (id, login, role) => api(`/workspaces/${id}/invitations`, { method: 'POST', body: { login, role } }),
  revokeInvitation: (id, invId) => api(`/workspaces/${id}/invitations/${invId}`, { method: 'DELETE' }),
  audit: (id) => api(`/workspaces/${id}/audit`),
  myInvitations: () => api('/workspaces/invitations/mine'),
  accept: (token) => api('/workspaces/invitations/accept', { method: 'POST', body: { token } }),
  decline: (invId) => api(`/workspaces/invitations/${invId}/decline`, { method: 'POST' }),
}

export const notificationService = {
  list: (params) => api('/notifications', { params }),
  unread: () => api('/notifications/unread-count'),
  read: (id) => api(`/notifications/${id}/read`, { method: 'POST' }),
  readAll: () => api('/notifications/read-all', { method: 'POST' }),
}

export const accountService = {
  exports: () => api('/account/exports'),
  requestExport: () => api('/account/exports', { method: 'POST' }),
  downloadUrl: (id) => `${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/account/exports/${id}/download`,
  remove: (confirm_login) => api('/account/delete', { method: 'POST', body: { confirm_login } }),
}

