/**
 * API client：axios 实例 + JWT 注入 + 401 登出。
 * baseURL /api/v1（与后端路由约定）。
 *
 * 鉴权模型：单一长效 access token（7 天）。不再做静默 refresh——SCF 冷启动下
 * refresh 链路偶发失败反而导致掉登录；token 过期即视为登录失效，直接登出。
 */

import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios"
import { clearSession, getToken, saveSession } from "../store/auth"
import type { DebugJobStatus, MetricDef, ProjectSample, SampleTrendPoint } from "../types"

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
  async updateProject(projectId: string, data: { isPublic?: boolean }) {
    return (await http.patch(`/projects/${projectId}`, data)).data.project
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
  async runOverview(runId: string): Promise<{
    verdict?: "pass" | "fail"
    score?: number
    metrics?: { DR: number; CPR: number; condR: number; avg_time_ms: number }
    metrics_raw?: Record<string, number>
    summary?: { total: number; passed: number; failed: number; skipped: number }
    summary_report?: {
      headline?: string
      highlights?: string[]
      issues?: Array<{ title?: string; detail?: string; severity?: string; files?: string[] }>
      suggestion?: string
    } | null
    items: Array<{
      external_sample_id: string
      score: number
      passed: boolean
      failures: Array<{ name: string; reason: string; top_issues?: string[]; files?: string[] }>
    }>
  }> {
    return (await http.get(`/runs/${runId}/overview`)).data.overview
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
    opts?: { packageRef?: string; taskId?: string; taskTitle?: string; apiKey?: string },
  ): Promise<{
    job_id: string
    status: string
    poll_url: string
    debug?: { request: Record<string, unknown>; response: Record<string, unknown> }
  }> {
    const qs = new URLSearchParams({ filename: file.name, rule_set_id: ruleSetId })
    if (opts?.packageRef) qs.set("package_ref", opts.packageRef)
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
  async getDebugOverview(jobId: string, apiKey?: string): Promise<Record<string, unknown>> {
    const qs = new URLSearchParams()
    if (apiKey) qs.set("api_key", apiKey)
    const suffix = qs.toString() ? `?${qs.toString()}` : ""
    return (await http.get(`/debug/jobs/${jobId}/overview${suffix}`)).data
  },
  // 规则集目录（GET /api/v1/rule-sets，构建期静态 catalog，含派生能力 llm/vision/kb）
  async debugRuleSets(): Promise<
    Array<{ id: string; name: string; description: string; capabilities: string[]; scopes: string[] }>
  > {
    return (await http.get("/debug/rule-sets")).data.rule_sets
  },

  /* ── 配置管理（场景包，Phase 3/4）─────────────────── */
  async scenarios(): Promise<Scenario[]> {
    return (await http.get("/scenarios")).data.scenarios as Scenario[]
  },
  async createScenario(id: string, name: string, description?: string): Promise<Scenario> {
    return (await http.post("/scenarios", { id, name, description })).data.scenario
  },
  async scenarioCatalog(scenarioId: string): Promise<ScenarioCatalog> {
    return (await http.get(`/scenarios/${scenarioId}/catalog`)).data as ScenarioCatalog
  },
  /** 场景默认指标定义 + 聚合策略（GET /scenarios/:id/defaults，前端无 hardcode）。 */
  async scenarioDefaults(scenarioId: string): Promise<MetricDef[]> {
    return (await http.get(`/scenarios/${scenarioId}/defaults`)).data.metric_definitions as MetricDef[]
  },
  async scenarioAggregationPolicy(scenarioId: string): Promise<Record<string, unknown> | null> {
    return (await http.get(`/scenarios/${scenarioId}/defaults`)).data.aggregation_policy ?? null
  },
  /** 一次 GET 拿完整 defaults（metric_definitions + aggregation_policy），供编辑器 loadDoc 组装。 */
  async scenarioDefaultsContent(
    scenarioId: string,
    version?: string,
  ): Promise<{ metric_definitions: MetricDef[]; aggregation_policy: Record<string, unknown> | null }> {
    const params = version ? `?version=${encodeURIComponent(version)}` : ""
    return (await http.get(`/scenarios/${scenarioId}/defaults${params}`)).data
  },
  /** 发布场景默认配置新版本（指标定义 + 聚合策略版本化；POST /scenarios/:id/defaults）。 */
  async publishDefaults(
    scenarioId: string,
    input: {
      version: string
      labels?: string[]
      metric_definitions?: unknown
      aggregation_policy?: unknown
    },
  ): Promise<{ asset: { assetId: string; version: string } }> {
    return (await http.post(`/scenarios/${scenarioId}/defaults`, input)).data
  },
  async listDefaultsVersions(
    scenarioId: string,
  ): Promise<Array<{ version: string; labels: string[]; contentHash: string; createdAt: string }>> {
    return (await http.get(`/scenarios/${scenarioId}/defaults/versions`)).data.versions
  },
  async promoteDefaultsLabels(scenarioId: string, version: string, labels: string[]): Promise<void> {
    await http.post(`/scenarios/${scenarioId}/defaults/versions/${version}/labels`, { labels })
  },
  /** 资产完整内容（评测规则浏览器/编辑器 diff 用）。 */
  async assetContent(
    scenarioId: string,
    kind: AssetKind,
    assetId: string,
    version?: string,
  ): Promise<Record<string, unknown>> {
    const params = version ? `?version=${encodeURIComponent(version)}` : ""
    return (await http.get(`/scenarios/${scenarioId}/${kind}/${assetId}/content${params}`)).data
      .content
  },
  async publishPackage(
    scenarioId: string,
    input: {
      asset_id: string
      version: string
      labels?: string[]
      name?: string
      description?: string
      content?: Record<string, unknown>
    },
  ): Promise<{ package: { packageId: string; scenarioId: string } }> {
    return (await http.post(`/scenarios/${scenarioId}/packages`, input)).data
  },
  async publishAsset(
    scenarioId: string,
    kind: AssetKind,
    input: {
      asset_id: string
      version: string
      labels?: string[]
      content?: Record<string, unknown>
      namespace?: string
      role?: string
      backend_type?: string
      backend_config?: Record<string, unknown>
    },
  ): Promise<{ asset: { assetId: string; version: string } }> {
    return (await http.post(`/scenarios/${scenarioId}/${kind}`, input)).data
  },
  async listAssetVersions(
    scenarioId: string,
    kind: AssetKind,
    assetId: string,
  ): Promise<Array<{ version: string; labels: string[]; contentHash: string; createdAt: string }>> {
    return (await http.get(`/scenarios/${scenarioId}/${kind}/${assetId}/versions`)).data.versions
  },
  async promoteAssetLabels(
    scenarioId: string,
    kind: AssetKind,
    assetId: string,
    version: string,
    labels: string[],
  ): Promise<void> {
    await http.post(`/scenarios/${scenarioId}/${kind}/${assetId}/versions/${version}/labels`, { labels })
  },

  /* ── 超管后台 ─────────────────────────────────────── */
  async adminOverview() {
    return (await http.get("/admin/stats/overview")).data
  },
  async adminTrends(limit = 100) {
    return (await http.get(`/admin/stats/trends?limit=${limit}`)).data as Array<{
      run_id: string
      created_at: string
      metrics?: Record<string, number> | null
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
  async adminListLlmModels(): Promise<LlmModelVO[]> {
    return (await http.get("/admin/llm-models")).data
  },
  async adminCreateLlmModel(input: LlmModelInput): Promise<LlmModelVO> {
    return (await http.post("/admin/llm-models", input)).data
  },
  async adminUpdateLlmModel(id: string, input: Partial<LlmModelInput>): Promise<LlmModelVO> {
    return (await http.patch(`/admin/llm-models/${id}`, input)).data
  },
  async adminDeleteLlmModel(id: string): Promise<void> {
    await http.delete(`/admin/llm-models/${id}`)
  },
  async adminSetDefaultLlmModel(id: string): Promise<LlmModelVO> {
    return (await http.post(`/admin/llm-models/${id}/set-default`)).data
  },
  async adminTestLlmModel(id: string): Promise<{ status: "success" | "failed"; detail: string; testedAt: string }> {
    return (await http.post(`/admin/llm-models/${id}/test`)).data
  },
  async adminExportLlmYaml(): Promise<string> {
    return (await http.post("/admin/llm-models/export-yaml", {}, { responseType: "text", transformResponse: (x) => x })).data
  },
  async aiOptimizePrompt(input: {
    instruction: string
    scenario?: string
    currentSystem?: string
    currentUserPrompt?: string
  }): Promise<{ system: string; userPrompt: string }> {
    return (await http.post("/ai/optimize-prompt", input)).data
  },
  async aiRecommendRules(input: {
    scenario?: string
    cascade?: Array<{ stage: string; name?: string }>
    existingRules?: Array<{ name?: string; method?: string; stage?: string }>
  }): Promise<{ rules: Record<string, unknown>[] }> {
    return (await http.post("/ai/recommend-rules", input)).data
  },
  async aiGenerateMetrics(input: { scenario?: string; description: string }): Promise<{ metricDefinitions: Record<string, unknown>[] }> {
    return (await http.post("/ai/generate-metrics", input)).data
  },
  async aiGeneratePolicy(input: {
    scenario?: string
    cascade?: Array<{ stage: string; name?: string }>
    metricDefinitions?: Array<{ id?: string; name?: string; threshold?: number | null; unit?: string | null }>
  }): Promise<{ aggregationPolicy: Record<string, unknown> | null }> {
    return (await http.post("/ai/generate-policy", input)).data
  },
}

export type AssetKind = "rule-sets" | "prompts" | "datasets"

export interface Scenario {
  id: string
  name: string
  description: string | null
  createdAt: string
}
export interface CatalogEntry {
  asset_id: string
  version: string
  labels: string[]
  name: string | null
  description: string | null
}
export interface DatasetCatalogEntry extends CatalogEntry {
  role: string
  backend_type: string
}
export interface ScenarioCatalog {
  scenario: { id: string; name: string; description: string | null }
  rule_sets: CatalogEntry[]
  prompts: CatalogEntry[]
  datasets: DatasetCatalogEntry[]
  packages: CatalogEntry[]
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
  totalSamples: number
  createdAt: string
  /** Phase 5 场景化指标（与 dr/cpr 并存，P5-8 清理遗留列后为唯一来源）*/
  metrics?: Record<string, number>
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

/* ── LLM 模型配置（docs/arch/13）+ 配置资产 AI 生成 ──────────── */
export interface LlmModelVO {
  id: string
  name: string
  provider: string // openai | anthropic
  baseUrl: string | null
  apiKeyMasked: string
  modelName: string
  isActive: boolean
  isDefault: boolean
  extra: Record<string, unknown> | null
  lastTestedAt: string | null
  lastTestStatus: string | null // success | failed | null
  lastTestError: string | null
  createdAt: string
  updatedAt: string
}
export interface LlmModelInput {
  name: string
  provider: string
  baseUrl?: string | null
  apiKey?: string
  modelName: string
  isActive?: boolean
  isDefault?: boolean
  extra?: Record<string, unknown> | null
}

export { saveSession }
