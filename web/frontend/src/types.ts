/** 与后端 /api/v1 契约对应的类型。 */

export interface AuthSession {
  access_token: string
  refresh_token: string
  expires_in: number
}

export interface User {
  id: string
  email: string
  name: string | null
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
    dr: number | null
    cpr: number | null
    avgReward: number | null
  } | null
}

export interface RunSummary {
  id: string
  externalRunId: string
  mode: string
  status: string
  totalSamples: number
  samples?: { externalSampleId: string }[]
  dr: number
  cpr: number
  avgReward: number
  condR: number
  avgTimeMs: number
  ruleSetVersion: string | null
  langfuseTraceId: string | null
  langfuseHost: string | null
  createdAt: string
}

export interface TrendPoint {
  run_id: string
  created_at: string
  DR: number
  CPR: number
  Reward: number
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
}

/** 项目下样本（课件）清单项（docs/arch/14）。 */
export interface ProjectSample {
  externalSampleId: string
  evalCount: number
  latestAt: string
  latestReward: number
  latestStatus: string
  latestContentHash: string | null
}

/** 样本走势点（某 externalSampleId 跨 run 的时间序列，docs/arch/14）。 */
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

/** API Key 列表/吊销回显（不含 secret）。callCount 为 BigInt 序列化的字符串。 */
export interface ApiKeySafe {
  id: string
  publicKey: string
  name: string
  expiresAt: string | null
  lastUsedAt: string | null
  lastIp: string | null
  callCount: string
  createdAt: string
  revokedAt: string | null
}

/** 签发响应：含一次性 plaintext secretKey。 */
export interface IssuedApiKey extends ApiKeySafe {
  secretKey: string
}
