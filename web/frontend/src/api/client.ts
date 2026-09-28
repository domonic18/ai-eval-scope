/**
 * API client：axios 实例 + JWT 注入 + 401 登出。
 * baseURL /api/v1（与后端路由约定）。
 *
 * 鉴权模型：单一长效 access token（7 天）。不再做静默 refresh——SCF 冷启动下
 * refresh 链路偶发失败反而导致掉登录；token 过期即视为登录失效，直接登出。
 */

import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios"
import { clearSession, getToken, saveSession } from "../store/auth"
import type {
  DebugJobStatus,
  LatestRunSnapshot,
  MetricDef,
  ProjectSample,
  SampleTrendPoint,
  SampleViewConfig,
} from "../types"

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
  async updateProject(
    projectId: string,
    data: { isPublic?: boolean; webhookUrl?: string | null; webhookSecret?: string },
  ) {
    return (await http.patch(`/projects/${projectId}`, data)).data.project
  },
  async testWebhook(projectId: string): Promise<{ sent: boolean; url: string | null }> {
    return (await http.post(`/projects/${projectId}/test-webhook`)).data
  },
  async getWebhookDeliveries(
    projectId: string,
    limit = 20,
  ): Promise<
    Array<{
      id: string
      jobId: string | null
      event: string
      url: string
      attempt: number
      success: boolean
      statusCode: number | null
      error: string | null
      durationMs: number | null
      requestBody: unknown | null
      responseBody: string | null
      createdAt: string
    }>
  > {
    return (await http.get(`/projects/${projectId}/webhook-deliveries?limit=${limit}`)).data
      .deliveries
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
      createdAt: string
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
  /** 已注册邮箱 → 直加入；未注册 → 建待接受邀请（对方注册后自动加入）。 */
  async inviteMember(orgId: string, email: string, role: string) {
    return (await http.post(`/orgs/${orgId}/members`, { email, role })).data.member as
      | { kind: "member"; userId: string; email: string; role: string }
      | { kind: "invitation"; email: string; role: string }
  },
  async listInvitations(orgId: string) {
    return (await http.get(`/orgs/${orgId}/invitations`)).data.invitations as import("../types").OrgInvitationRow[]
  },
  async resendInvitation(orgId: string, id: string) {
    return (await http.post(`/orgs/${orgId}/invitations/${id}/resend`)).data as { resent: boolean }
  },
  async revokeInvitation(orgId: string, id: string) {
    return (await http.post(`/orgs/${orgId}/invitations/${id}/revoke`)).data as { revoked: boolean }
  },
  async removeMember(orgId: string, userId: string) {
    return (await http.delete(`/orgs/${orgId}/members/${userId}`)).data
  },
  /** 角色变更 / 所有权转移（demoteSelf：提升他人同时降级自己，事务原子）。 */
  async updateMemberRole(orgId: string, userId: string, role: string, demoteSelf = false) {
    return (await http.patch(`/orgs/${orgId}/members/${userId}`, { role, demoteSelf })).data as {
      userId: string
      role: string
      selfDemoted: boolean
    }
  },
  async projectRuns(projectId: string, page = 1, size = 50) {
    return (await http.get(`/projects/${projectId}/runs`, { params: { page, size } })).data
  },
  async projectTrends(projectId: string, limit = 50) {
    return (await http.get(`/projects/${projectId}/trends`, { params: { limit } })).data
  },
  /** 快照语义「最近一次上报」（arch/09 §9.6）：run 与场景指标定义已服务端配对。 */
  async projectLatestRun(projectId: string): Promise<LatestRunSnapshot> {
    return (await http.get(`/projects/${projectId}/latest-run`)).data
  },
  async runDetail(runId: string) {
    return (await http.get(`/runs/${runId}`)).data.run
  },
  async runOverview(runId: string): Promise<{
    verdict?: "pass" | "fail"
    score?: number
    metrics?: Record<string, number>
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
  /**
   * 运行导出（arch/09 §9.8）：后端流式 zip 自描述 bundle。
   * axios blob + 长 timeout（optionalAuth 只认 Bearer 头，裸 <a> 带不上凭证）。
   */
  async runDownload(runId: string): Promise<void> {
    const res = await http.get(`/runs/${runId}/export`, {
      responseType: "blob",
      timeout: 300000,
    })
    const disposition = (res.headers["content-disposition"] as string | undefined) ?? ""
    const m = /filename="?([\w.-]+)"?/.exec(disposition)
    const name = m?.[1] ?? `run-${runId}.zip`
    const url = URL.createObjectURL(res.data as Blob)
    const a = document.createElement("a")
    a.href = url
    a.download = name
    a.click()
    URL.revokeObjectURL(url)
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
  async scenarios(source?: "official" | "auto_ingest"): Promise<Scenario[]> {
    const params = source ? { source } : undefined
    return (await http.get("/scenarios", { params })).data.scenarios as Scenario[]
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
  async listDefaultsVersions(
    scenarioId: string,
  ): Promise<Array<{ version: string; labels: string[]; contentHash: string; createdAt: string }>> {
    return (await http.get(`/scenarios/${scenarioId}/defaults/versions`)).data.versions
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
  async listAssetVersions(
    scenarioId: string,
    kind: AssetKind,
    assetId: string,
  ): Promise<Array<{ version: string; labels: string[]; contentHash: string; createdAt: string }>> {
    return (await http.get(`/scenarios/${scenarioId}/${kind}/${assetId}/versions`)).data.versions
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
  /** 场景样本视图配置（arch/09 §9.7 呈现配置链；platformAdmin）。 */
  async adminGetSampleView(scenarioId: string): Promise<{ scenarioId: string; sampleView: SampleViewConfig | null }> {
    return (await http.get(`/admin/scenarios/${scenarioId}/sample-view`)).data
  },
  async adminSetSampleView(scenarioId: string, config: SampleViewConfig): Promise<{ scenarioId: string; sampleView: SampleViewConfig }> {
    return (await http.put(`/admin/scenarios/${scenarioId}/sample-view`, config)).data
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
  async listOrgSecrets(orgId: string): Promise<OrgSecret[]> {
    return (await http.get(`/orgs/${orgId}/secrets`)).data.secrets
  },
  async putOrgSecret(orgId: string, name: string, value: string): Promise<OrgSecret> {
    return (await http.put(`/orgs/${orgId}/secrets/${encodeURIComponent(name)}`, { value })).data
  },
  async deleteOrgSecret(orgId: string, name: string): Promise<void> {
    await http.delete(`/orgs/${orgId}/secrets/${encodeURIComponent(name)}`)
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
}

export type AssetKind = "rule-sets" | "prompts" | "datasets" | "task-sets" | "sut-configs"

export interface Scenario {
  id: string
  name: string
  description: string | null
  /** official = 管理员创建/脚本导入；auto_ingest = run 事件补缺注册（不进配置中心默认视图） */
  source: "official" | "auto_ingest"
  createdAt: string
  _count?: {
    packages: number
    ruleSets: number
    prompts: number
    datasets: number
    taskSets: number
    sutConfigs: number
    defaults: number
  }
}
export interface CatalogEntry {
  asset_id: string
  version: string
  labels: string[]
  name: string | null
  description: string | null
  accept?: string[]
}
export interface DatasetCatalogEntry extends CatalogEntry {
  role: string
  backend_type: string
}
/** 任务集（考卷）catalog 条目：task_count = content.tasks 数量。 */
export interface TaskSetCatalogEntry extends CatalogEntry {
  task_count: number
}
/** SUT 接入配置 catalog 条目：channel 如 agent_protocol；content 仅 sut: 子树（无真凭证）。 */
export interface SutCatalogEntry extends CatalogEntry {
  channel: string | null
}
export interface ScenarioCatalog {
  scenario: { id: string; name: string; description: string | null }
  rule_sets: CatalogEntry[]
  prompts: CatalogEntry[]
  datasets: DatasetCatalogEntry[]
  task_sets: TaskSetCatalogEntry[]
  sut_configs: SutCatalogEntry[]
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
/** org 级平台 Secret（值写后不可读，列表仅名称与时间） */
export interface OrgSecret {
  name: string
  createdAt: string
  updatedAt: string
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
  scenarioId: string | null
  mode: string
  status: string
  totalSamples: number
  createdAt: string
  /** Phase 5 场景化指标（与 dr/cpr 并存，P5-8 清理遗留列后为唯一来源）*/
  metrics?: Record<string, number>
  /** 行级 defs 配对（docs/plan/08 批次 C）：锚定该 run 自带快照，无快照老 run 走场景 defaults 兜底 */
  metricDefinitions?: MetricDef[]
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
  provider: string // openai | anthropic | noul（decision 判定专线行）
  role: string // text | vision | agent | decision（arch/16 §6.2-四，executor 按角色拉取）
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
  role?: string // text | vision | agent | decision
  baseUrl?: string | null
  apiKey?: string
  modelName: string
  isActive?: boolean
  isDefault?: boolean
  extra?: Record<string, unknown> | null
}

export { saveSession }
