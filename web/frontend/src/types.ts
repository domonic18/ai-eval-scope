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
