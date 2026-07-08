/**
 * API client：axios 实例 + JWT 注入 + 401 登出。
 * baseURL /api/v1（与后端路由约定）。
 *
 * 鉴权模型：单一长效 access token（7 天）。不再做静默 refresh——SCF 冷启动下
 * refresh 链路偶发失败反而导致掉登录；token 过期即视为登录失效，直接登出。
 */

import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios"
import { clearSession, getToken, saveSession } from "../store/auth"
import type { DebugJobStatus, ProjectSample, SampleTrendPoint } from "../types"

export const http = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
})

// 注入 access_token
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const tok = getToken()
  if (tok) config.headers.set("Authorization", `Bearer ${tok}`)
  return config
})

// 401 → token 失效，清 session 跳登录（不再静默刷新）
http.interceptors.response.use(
  (r) => r,
  (error: AxiosError) => {
    if (error.response?.status === 401 && !error.config?.url?.includes("/auth/")) {
      clearSession()
      if (location.pathname !== "/login") location.href = "/login"
    }
    return Promise.reject(error)
  },
)

// ── 便捷封装 ──
export const api = {
  async me() {
    return (await http.get("/auth/me")).data
  },
  async login(email: string, password: string) {
    return (await http.post("/auth/login", { email, password })).data
  },
  async register(email: string, password: string, name: string) {
    return (await http.post("/auth/register", { email, password, name })).data
  },
  async ssoConfig() {
    return (await http.get("/auth/sso/config")).data as { enabled: boolean }
  },
  async ssoLogin() {
    return (await http.post("/auth/sso/login")).data as { redirect_url: string }
  },
  async ssoExchange(code: string) {
    return (await http.post("/auth/sso/exchange", { code })).data
  },
  async dashboard(orgId: string) {
    return (await http.get(`/orgs/${orgId}/projects`)).data.projects
  },
  async project(id: string) {
    return (await http.get(`/projects/${id}`)).data.project
  },
  async createProject(orgId: string, name: string, slug: string) {
    return (await http.post(`/orgs/${orgId}/projects`, { name, slug })).data.project
  },
  async archiveProject(projectId: string) {
    return (await http.post(`/projects/${projectId}/archive`)).data.project
  },
  async deleteProject(projectId: string) {
    return (await http.delete(`/projects/${projectId}`)).data
  },
  async createOrg(name: string) {
    return (await http.post("/orgs", { name })).data.org as {
      id: string
      name: string
      slug: string
    }
  },
  async teams() {
    return (await http.get("/teams")).data.teams as {
      id: string
      name: string
      slug: string
      isMember: boolean
      requestStatus: string | null
    }[]
  },
  async myJoinRequests() {
    return (await http.get("/me/join-requests")).data.requests as {
      id: string
      orgId: string
      status: string
      message: string | null
      org: { name: string; slug: string }
    }[]
  },
  async requestJoin(orgId: string, message?: string) {
    return (await http.post(`/orgs/${orgId}/join-requests`, { message })).data.request as {
      id: string
      orgId: string
      status: string
    }
  },
  async orgJoinRequests(orgId: string) {
    return (await http.get(`/orgs/${orgId}/join-requests`)).data.requests as {
      id: string
      status: string
      message: string | null
      user: { id: string; email: string; name: string | null }
    }[]
  },
  async approveJoin(orgId: string, reqId: string) {
    return (await http.post(`/orgs/${orgId}/join-requests/${reqId}/approve`)).data
  },
  async rejectJoin(orgId: string, reqId: string) {
    return (await http.post(`/orgs/${orgId}/join-requests/${reqId}/reject`)).data
  },
  async listMembers(orgId: string) {
    return (await http.get(`/orgs/${orgId}/members`)).data.members
  },
  async inviteMember(orgId: string, email: string, role: string) {
    return (await http.post(`/orgs/${orgId}/members`, { email, role })).data.member
  },
  async removeMember(orgId: string, userId: string) {
    return (await http.delete(`/orgs/${orgId}/members/${userId}`)).data
  },
  async projectRuns(projectId: string, page = 1, size = 50) {
    return (await http.get(`/projects/${projectId}/runs`, { params: { page, size } })).data
  },
  async projectTrends(projectId: string, limit = 50) {
    return (await http.get(`/projects/${projectId}/trends`, { params: { limit } })).data
  },
  async runDetail(runId: string) {
    return (await http.get(`/runs/${runId}`)).data.run
  },
  async sampleDetail(runId: string, sampleId: string) {
    return (await http.get(`/runs/${runId}/samples/${sampleId}`)).data.sample
  },
  async listSamples(projectId: string) {
    return (await http.get(`/projects/${projectId}/samples`)).data as ProjectSample[]
  },
  async sampleTrends(projectId: string, sampleId: string, limit = 100) {
    return (
      await http.get(`/projects/${projectId}/sample-trends`, {
        params: { sample_id: sampleId, limit },
      })
    ).data as SampleTrendPoint[]
  },
  async deleteRun(runId: string) {
    return (await http.delete(`/runs/${runId}`)).data
  },
  async listKeys(projectId: string) {
    return (await http.get(`/projects/${projectId}/keys`)).data.keys
  },
  async createKey(projectId: string, name: string) {
    return (await http.post(`/projects/${projectId}/keys`, { name })).data.key
  },
  async revokeKey(projectId: string, keyId: string) {
    return (await http.post(`/projects/${projectId}/keys/${keyId}/revoke`)).data.key
  },
  artifactUrl(artifactId: string): string {
    return `/api/v1/artifacts/${artifactId}`
  },
  async artifactPreview(
    artifactId: string,
  ): Promise<{ url: string; contentType: string; filename: string }> {
    return (await http.get(`/artifacts/${artifactId}/preview`)).data
  },
  // ── 调试台：提交到 Web 后端 /api/v1/debug/jobs（登录即可用，项目由 API Key 解析）──
  async submitDebugJob(
    file: File,
    ruleSetId: string,
    opts?: { taskId?: string; taskTitle?: string; apiKey?: string },
  ): Promise<{
    job_id: string
    status: string
    poll_url: string
    debug?: { request: Record<string, unknown>; response: Record<string, unknown> }
  }> {
    const qs = new URLSearchParams({ filename: file.name, rule_set_id: ruleSetId })
    if (opts?.taskId) qs.set("task_id", opts.taskId)
    if (opts?.taskTitle) qs.set("task_title", opts.taskTitle)
    if (opts?.apiKey) qs.set("api_key", opts.apiKey)
    return (
      await http.post(`/debug/jobs?${qs.toString()}`, file, {
        headers: { "Content-Type": "application/octet-stream" },
        timeout: 60000,
      })
    ).data
  },
  async getDebugJob(jobId: string, apiKey?: string): Promise<DebugJobStatus> {
    const qs = new URLSearchParams()
    if (apiKey) qs.set("api_key", apiKey)
    const suffix = qs.toString() ? `?${qs.toString()}` : ""
    return (await http.get(`/debug/jobs/${jobId}${suffix}`)).data
  },
  // 规则集目录（GET /api/v1/rule-sets，构建期静态 catalog，含派生能力 llm/vision/kb）
  async debugRuleSets(): Promise<
    Array<{ id: string; name: string; description: string; capabilities: string[]; scopes: string[] }>
  > {
    return (await http.get("/debug/rule-sets")).data.rule_sets
  },

  /* ── 超管后台 ─────────────────────────────────────── */
  async adminOverview() {
    return (await http.get("/admin/stats/overview")).data
  },
  async adminTrends(limit = 100) {
    return (await http.get(`/admin/stats/trends?limit=${limit}`)).data as Array<{
      run_id: string
      created_at: string
      DR: number
      CPR: number
      Reward: number
    }>
  },
  async adminScoreDistribution() {
    return (await http.get("/admin/stats/score-distribution")).data as Array<{
      bucket: string
      count: number
    }>
  },
  async adminListUsers(opts: { search?: string; status?: string; page?: number } = {}) {
    const qs = new URLSearchParams()
    if (opts.search) qs.set("search", opts.search)
    if (opts.status) qs.set("status", opts.status)
    qs.set("page", String(opts.page ?? 1))
    return (await http.get(`/admin/users?${qs.toString()}`)).data as {
      items: AdminUser[]
      total: number
      page: number
      size: number
    }
  },
  async adminUpdateUser(
    id: string,
    data: { role?: string; status?: string; name?: string | null },
  ) {
    return (await http.patch(`/admin/users/${id}`, data)).data
  },
  async adminDeleteUser(id: string) {
    return (await http.delete(`/admin/users/${id}`)).data
  },
  async adminListOrgs(opts: { search?: string; page?: number } = {}) {
    const qs = new URLSearchParams()
    if (opts.search) qs.set("search", opts.search)
    qs.set("page", String(opts.page ?? 1))
    return (await http.get(`/admin/orgs?${qs.toString()}`)).data as {
      items: AdminOrg[]
      total: number
      page: number
      size: number
    }
  },
  async adminDeleteOrg(id: string) {
    return (await http.delete(`/admin/orgs/${id}`)).data
  },
  async adminListProjects(opts: { search?: string; archived?: boolean; page?: number } = {}) {
    const qs = new URLSearchParams()
    if (opts.search) qs.set("search", opts.search)
    if (opts.archived !== undefined) qs.set("archived", String(opts.archived))
    qs.set("page", String(opts.page ?? 1))
    return (await http.get(`/admin/projects?${qs.toString()}`)).data as {
      items: AdminProject[]
      total: number
      page: number
      size: number
    }
  },
  async adminDeleteProject(id: string) {
    return (await http.delete(`/admin/projects/${id}`)).data
  },
  async adminListRuns(opts: { status?: string; search?: string; page?: number } = {}) {
    const qs = new URLSearchParams()
    if (opts.status) qs.set("status", opts.status)
    if (opts.search) qs.set("search", opts.search)
    qs.set("page", String(opts.page ?? 1))
    return (await http.get(`/admin/runs?${qs.toString()}`)).data as {
      items: AdminRun[]
      total: number
      page: number
      size: number
    }
  },
  async adminDeleteRun(id: string) {
    return (await http.delete(`/admin/runs/${id}`)).data
  },
  async adminListArtifacts(opts: { kind?: string; page?: number } = {}) {
    const qs = new URLSearchParams()
    if (opts.kind) qs.set("kind", opts.kind)
    qs.set("page", String(opts.page ?? 1))
    return (await http.get(`/admin/artifacts?${qs.toString()}`)).data as {
      items: AdminArtifact[]
      total: number
      page: number
      size: number
    }
  },
  async adminDeleteArtifact(id: string) {
    return (await http.delete(`/admin/artifacts/${id}`)).data
  },
  async adminBatchDeleteArtifacts(ids: string[]) {
    return (await http.delete("/admin/artifacts", { data: { ids } })).data as {
      ok: boolean
      deleted: number
    }
  },
  async adminListAudit(opts: { action?: string; page?: number } = {}) {
    const qs = new URLSearchParams()
    if (opts.action) qs.set("action", opts.action)
    qs.set("page", String(opts.page ?? 1))
    return (await http.get(`/admin/audit?${qs.toString()}`)).data as {
      items: AdminAuditRow[]
      total: number
      page: number
      size: number
    }
  },
}

export interface AdminUser {
  id: string
  email: string
  name: string | null
  role: string
  status: string
  createdAt: string
  authType?: string
  _count?: { memberships: number }
}
export interface AdminOrg {
  id: string
  name: string
  slug: string
  createdBy: string
  createdAt: string
  memberCount: number
  projectCount: number
  runCount: number
}
export interface AdminProject {
  id: string
  name: string
  slug: string
  orgId: string
  archivedAt: string | null
  createdAt: string
  org: { id: string; name: string }
  _count: { runs: number; apiKeys: number }
}
export interface AdminRun {
  id: string
  externalRunId: string
  mode: string
  status: string
  dr: number
  cpr: number
  avgReward: number
  totalSamples: number
  createdAt: string
  project: { id: string; name: string; org: { id: string; name: string } }
}
export interface AdminArtifact {
  id: string
  kind: string
  sizeBytes: number
  contentType: string
  originalName: string | null
  createdAt: string
  project: { id: string; name: string }
  run: { id: string; externalRunId: string }
}
export interface AdminAuditRow {
  id: string
  orgId: string | null
  actorUserId: string | null
  action: string
  targetType: string | null
  targetId: string | null
  createdAt: string
}

export { saveSession }
