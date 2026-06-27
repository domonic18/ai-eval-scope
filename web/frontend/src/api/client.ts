/**
 * API client：axios 实例 + JWT 注入 + 401 刷新拦截器。
 * baseURL /api/v1（与后端路由约定）。
 */

import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios"
import { clearSession, getRefreshToken, getToken, saveSession } from "../store/auth"

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

// 401 → 尝试用 refresh_token 刷新一次后重试
let refreshing: Promise<boolean> | null = null

async function doRefresh(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  try {
    const resp = await axios.post("/api/v1/auth/refresh", { refresh_token: refresh })
    const cur = localStorage.getItem("agent_eval_session")
    if (cur) {
      const stored = JSON.parse(cur)
      saveSession({ ...resp.data, user: stored.user })
    }
    return true
  } catch {
    return false
  }
}

http.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean }
    if (error.response?.status === 401 && !original._retried && !original.url?.includes("/auth/")) {
      original._retried = true
      refreshing =
        refreshing ||
        doRefresh().finally(() => {
          refreshing = null
        })
      const ok = await refreshing
      if (ok) return http(original)
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
}

export { saveSession }
