/** 与后端 /api/v1 契约对应的类型。 */

export interface AuthSession {
  access_token: string
  expires_in: number
}

export interface User {
  id: string
  email: string
  name: string | null
  role?: string
  platformAdmin?: boolean
  status?: string
}

export interface Membership {
  orgId: string
  role: string
  org: { id: string; name: string; slug: string }
}

/** 组织成员行（GET /orgs/:org/members，成员页表格）。 */
export interface MemberRow {
  userId: string
  role: string
  email: string
  name: string | null
  joinedAt: string
  /** 最近登录时间（「最近活跃」列）；null = 从未登录。 */
  lastActive: string | null
}

/** 待接受邀请行（GET /orgs/:org/invitations，owner 专属）。 */
export interface OrgInvitationRow {
  id: string
  email: string
  role: string
  createdAt: string
  resentAt: string | null
  inviter: { id: string; name: string | null; email: string }
}

/** 加入申请行（GET /orgs/:org/join-requests，owner 待审批区块）。 */
export interface JoinRequestRow {
  id: string
  status: string
  message: string | null
  createdAt: string
  user: { id: string; email: string; name: string | null }
}

export interface DashboardProject {
  id: string
  name: string
  slug: string
  description: string | null
  createdAt: string
  runCount: number
  ownerName: string
  latestRun: {
    runId: string
    createdAt: string | null
    metrics?: Record<string, number> | null
    scenarioId: string | null
    /** 行级 defs 配对（docs/plan/08 批次 C）：锚定该 run 自带快照，无快照老 run 走场景 defaults 兜底 */
    metricDefinitions?: MetricDef[]
  } | null
}

export interface RunSummary {
  id: string
  externalRunId: string
  scenarioId: string | null
  mode: string
  status: string
  totalSamples: number
  samples?: { externalSampleId: string }[]
  /** Phase 5 场景化指标（权威，键=MetricDefinition.id） */
  metrics?: Record<string, number>
  metricDefinitions?: MetricDef[]
  ruleSetVersion: string | null
  langfuseTraceId: string | null
  langfuseHost: string | null
  createdAt: string
}

export interface TrendPoint {
  run_id: string
  created_at: string
  metrics?: Record<string, number>
}

export interface SampleSummary {
  id: string
  externalSampleId: string
  status: string
  reward: number
  sFormat: number
  sCommon: number
  sSoft: number
  sPref: number
  /** Phase 5 场景化样本指标 */
  metrics?: Record<string, number>
}

/** Phase 5 场景化指标定义（来自 RunConfigSnapshot.metric_definitions）。 */
export interface MetricDef {
  id: string
  name?: string
  expression?: string
  threshold?: number | null
  unit?: string | null
  /** 一句话大白话描述（摘要报告用，非技术用户可读） */
  summary?: string
  /** 可选指标说明（hover ? 提示，对齐旧 METRIC_EXPLAIN）；由定义驱动，缺省不显示 */
  explain?: MetricExplain
}

/** 可序列化的指标说明（驱动 ? hover 提示，含彩色强调）。 */
export interface MetricExplain {
  title: string
  rows: MetricExplainRow[]
}
export interface MetricExplainRow {
  dt: string
  dd: string
  /** dd 的强调色：primary/danger/success/warning/default */
  tone?: "default" | "primary" | "danger" | "success" | "warning"
}

/** 快照语义「最近一次上报」（docs/arch/09 §9.6）：run 与其场景指标定义服务端原子配对下发。 */
export interface LatestRunSnapshot {
  run: RunSummary | null
  metricDefinitions: MetricDef[]
  /** 血缘 meta（docs/plan/08 批次 C）：defs 解析来源 + 锚定版本 hash（暂无 UI 消费，供核查） */
  defsSource?: "run-snapshot" | "scenario-defaults" | "none"
  snapshotHash?: string | null
  defaultsHash?: string | null
}

/** 样本视图 tab 词表（docs/arch/09 §9.7；与后端 SAMPLE_VIEW_TABS 同源）。 */
export type SampleViewTab = "doc" | "task" | "transcript" | "shot" | "trace"

/** 场景样本视图呈现配置（场景级，管理端可编辑；null = 前端机械兜底）。 */
export interface SampleViewConfig {
  tabs: SampleViewTab[]
  labels?: { doc?: string }
}

/** 项目下样本（课件）清单项（docs/arch/09 §9.4）。 */
export interface ProjectSample {
  externalSampleId: string
  evalCount: number
  latestAt: string
  latestReward: number
  latestStatus: string
  latestContentHash: string | null
}

/** 样本走势点（某 externalSampleId 跨 run 的时间序列，docs/arch/09 §9.4；指标为场景化 JSONB）。 */
export interface SampleTrendPoint {
  run_id: string
  created_at: string
  reward: number
  status: string
  content_hash: string | null
  metrics?: Record<string, number>
}

export interface ConstraintRow {
  id: string
  constraintId: string
  ruleId: string | null
  name: string
  tier: string
  status: string
  passed: boolean
  score: number
  rawScore: number | null
  reason: string
  details: Record<string, unknown> | null
  durationMs: number
  judgeProvider: string | null
  judgeModel: string | null
  moduleResults: Array<Record<string, unknown>> | null
}

export interface ArtifactRow {
  id: string
  kind: string
  contentType: string
  sizeBytes: number
  originalName: string | null
}

/** API Key 列表/吊销回显（不含明文 token）。callCount 为 BigInt 序列化的字符串。 */
export interface ApiKeySafe {
  id: string
  tokenPreview: string
  name: string
  expiresAt: string | null
  lastUsedAt: string | null
  lastIp: string | null
  callCount: string
  createdAt: string
  revokedAt: string | null
}

/** 签发响应：含一次性 plaintext token。 */
export interface IssuedApiKey extends ApiKeySafe {
  token: string
}

/** 调试台：eval job 任务态（GET /api/v1/jobs/{id} 透传）。 */
export interface DebugJobStatus {
  job_id: string
  status: string // queued | running | completed | failed
  project_id?: string
  input_kind?: string // upload | inline
  scope?: string // unit | single
  rule_set_id?: string
  run_id?: string | null
  web_run_url?: string | null
  metrics?: {
    run_id?: string
    metrics?: Record<string, number>
    total_samples?: number
    failure_breakdown?: Record<string, number>
  } | null
  error?: { message?: string; traceback?: string } | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}
