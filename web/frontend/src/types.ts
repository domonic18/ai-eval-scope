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
  } | null
}

export interface RunSummary {
  id: string
  externalRunId: string
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

/** 项目下样本（课件）清单项（docs/arch/09 §9.4）。 */
export interface ProjectSample {
  externalSampleId: string
  evalCount: number
  latestAt: string
  latestReward: number
  latestStatus: string
  latestContentHash: string | null
}

/** 样本走势点（某 externalSampleId 跨 run 的时间序列，docs/arch/09 §9.4）。 */
export interface SampleTrendPoint {
  run_id: string
  created_at: string
  reward: number
  s_format: number
  s_common: number
  s_soft: number
  s_pref: number
  status: string
  content_hash: string | null
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
  moduleResults: Record<string, unknown> | null
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
    metrics?: {
      DR?: number
      CPR?: number
      condR?: number
      avg_reward?: number
      avg_soft?: number
      avg_pref?: number
      avg_time_ms?: number
      llm_skipped?: number
    }
    total_samples?: number
    failure_breakdown?: Record<string, number>
  } | null
  error?: { message?: string; traceback?: string } | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}
