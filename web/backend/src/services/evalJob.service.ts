/**
 * 评测任务提交 / 查询服务（docs/arch/09 §7.7 / 12）。
 *
 * 提交流程：物化输入 → 上传对象存储 → 签发 presigned GET → 写 eval_jobs(queued)
 *           → SCF Invoke Event 触发 executor（生产）。
 *
 * SCF 未启用时仅入队，由 executor worker 模式轮询（本地开发）。
 * executor 不持对象存储凭据：经 presigned GET URL 下载输入。
 */

import crypto from "crypto"
import type { EvalJob } from "@prisma/client"
import { getConfig } from "../config"
import { getObjectStorage } from "../infra/objectStorage"
import {
  materializeInline,
  materializeUpload,
  type MaterializedInput,
} from "../infra/inputMaterialize"
import { invokeScf, type ScfInvokePayload } from "../infra/scf"
import { PlatformError } from "../middleware/errorHandler"
import { EvalJobRepository } from "../repositories/evalJob.repository"
import { QueryRepository } from "../repositories/query.repository"
import type { Tenant } from "../repositories/base.repository"

export interface SubmitInput {
  // multipart 文件
  filename?: string
  fileBytes?: Buffer
  // 内联 JSON
  inlineFilename?: string
  inlineText?: string
  // 元数据
  ruleSetId: string
  taskId?: string
  taskTitle?: string
  taskSubject?: string
}

export interface SubmitResult {
  job_id: string
  status: "queued"
  project_id: string
  poll_url: string
  scf_request_id?: string
}

/**
 * 对外 job DTO（snake_case，对齐 integration.md / docs/arch/12 §6.3 契约）。
 * 仅暴露文档字段；input_object_key / input_presigned_url / api_key_id / scf_request_id
 * 等内部字段不外泄（input_presigned_url 为短期输入下载 URL，尤不应泄露）。
 */
export interface JobDto {
  job_id: string
  status: string
  project_id: string
  org_id: string
  input_kind: string
  scope: string
  rule_set_id: string
  task_id: string | null
  task_title: string | null
  task_subject: string | null
  run_id: string | null
  web_run_url: string | null
  metrics: unknown
  error: unknown
  created_at: Date
  started_at: Date | null
  finished_at: Date | null
}

/** Prisma EvalJob（camelCase）→ 对外 snake_case DTO。 */
export function serializeJob(job: EvalJob): JobDto {
  return {
    job_id: job.id,
    status: job.status,
    project_id: job.projectId,
    org_id: job.orgId,
    input_kind: job.inputKind,
    scope: job.scope,
    rule_set_id: job.ruleSetId,
    task_id: job.taskId,
    task_title: job.taskTitle,
    task_subject: job.taskSubject,
    run_id: job.runId,
    web_run_url: job.webRunUrl,
    metrics: job.metrics,
    error: job.error,
    created_at: job.createdAt,
    started_at: job.startedAt,
    finished_at: job.finishedAt,
  }
}

function extOf(filename: string, scope: "single" | "unit"): string {
  const dot = filename.lastIndexOf(".")
  if (dot >= 0) return filename.slice(dot)
  return scope === "unit" ? ".zip" : ".md"
}

function buildObjectKey(projectId: string, jobId: string, mat: MaterializedInput): string {
  return `projects/${projectId}/eval/jobs/${jobId}/input${extOf(mat.filename, mat.scope)}`
}

// ── 速览（overview，docs/arch/12 §6.6）──────────────────────────────
// 第三方"过没过 / 多少分 / 各项失败原因"的轻量结构化视图；深度详情走 iframe。

export interface OverviewFailure {
  name: string
  reason: string
}
export interface OverviewItem {
  external_sample_id: string
  score: number
  passed: boolean
  failures: OverviewFailure[]
}
export interface OverviewResult {
  job_id: string
  run_id: string | null
  status: string
  web_run_url: string | null
  error: unknown
  verdict?: "pass" | "fail"
  score?: number
  metrics?: { DR: number; CPR: number; condR: number; avg_time_ms: number }
  summary?: { total: number; passed: number; failed: number; skipped: number }
  dimension_pass?: { format: number; commonsense: number; soft: number; preference: number }
  items: OverviewItem[]
}

type OverviewSample = {
  id: string
  externalSampleId: string
  status: string
  reward: number
  sFormat: number
  sCommon: number
  sSoft: number
  sPref: number
  constraintResults: { name: string; reason: string; tier: string }[]
}
type OverviewRun = {
  externalRunId: string
  dr: number
  cpr: number
  condR: number
  avgReward: number
  avgTimeMs: number
  totalSamples: number
  thresholds: unknown
  samples: OverviewSample[]
}

/** 阈值容错取数：兼容 DR/dr、CPR/cpr、avg_reward/avgReward/Reward 多种键；缺失给默认。 */
function thresholdOf(t: unknown, keys: string[], fallback: number): number {
  const obj = (t ?? {}) as Record<string, unknown>
  for (const k of keys) {
    const v = obj[k]
    if (typeof v === "number" && Number.isFinite(v)) return v
  }
  return fallback
}

function isPassStatus(status: string): boolean {
  return status === "pass" || status === "passed"
}

/**
 * 纯函数：由 run（含样本 + 未通过约束）构造速览 DTO。
 * - verdict：核心指标达标（DR/CPR/Reward，阈值取 run.thresholds 或默认 0.95/0.9/0.8）
 *   且无 hard_gate 失败 → pass；否则 fail。
 * - dimension_pass：各阶段达标样本数（与前端 lib/eval.tsx 口径一致：format≥1 / commonsense>0 / soft≥0.6 / pref≥0.6）。
 */
export function buildJobOverview(
  base: Pick<OverviewResult, "job_id" | "run_id" | "status" | "web_run_url" | "error">,
  run: OverviewRun,
): OverviewResult {
  const samples = run.samples ?? []
  const passedN = samples.filter((s) => isPassStatus(s.status)).length
  const failedN = samples.filter((s) => s.status === "fail" || s.status === "failed").length
  const skippedN = samples.filter((s) => s.status === "skip" || s.status === "skipped").length

  const hasHardGateFail = samples.some((s) =>
    s.constraintResults.some((c) => c.tier === "hard_gate"),
  )
  const drT = thresholdOf(run.thresholds, ["DR", "dr"], 0.95)
  const cprT = thresholdOf(run.thresholds, ["CPR", "cpr"], 0.9)
  const rewT = thresholdOf(run.thresholds, ["avg_reward", "avgReward", "Reward"], 0.8)
  const metricsOk = run.dr >= drT && run.cpr >= cprT && run.avgReward >= rewT
  const verdict: "pass" | "fail" = metricsOk && !hasHardGateFail ? "pass" : "fail"

  return {
    ...base,
    run_id: run.externalRunId,
    status: "completed",
    verdict,
    score: run.avgReward,
    metrics: { DR: run.dr, CPR: run.cpr, condR: run.condR, avg_time_ms: run.avgTimeMs },
    summary: {
      total: run.totalSamples || samples.length,
      passed: passedN,
      failed: failedN,
      skipped: skippedN,
    },
    dimension_pass: {
      format: samples.filter((s) => s.sFormat >= 1).length,
      commonsense: samples.filter((s) => s.sCommon > 0).length,
      soft: samples.filter((s) => s.sSoft >= 0.6).length,
      preference: samples.filter((s) => s.sPref >= 0.6).length,
    },
    items: samples.map((s) => ({
      external_sample_id: s.externalSampleId,
      score: s.reward,
      passed: isPassStatus(s.status),
      failures: s.constraintResults.map((c) => ({ name: c.name, reason: c.reason })),
    })),
  }
}

export function createEvalJobService(tenant: Tenant) {
  const repo = new EvalJobRepository(tenant)
  const storage = getObjectStorage()

  async function submit(input: SubmitInput): Promise<SubmitResult> {
    if (!tenant.projectId || !tenant.orgId || !tenant.apiKeyId) {
      throw new PlatformError("missing tenant context (project/org/apiKey)", {
        status: 403,
        code: "FORBIDDEN",
      })
    }
    const projectId = tenant.projectId
    const jobId = crypto.randomUUID()

    // 物化输入 + scope 探测
    const mat = input.fileBytes
      ? materializeUpload(input.filename || "input", input.fileBytes)
      : materializeInline(input.inlineFilename || "input.md", input.inlineText || "")

    // 上传对象存储 + 签发短期 presigned GET（executor 下载用，不持凭据）
    const objectKey = buildObjectKey(projectId, jobId, mat)
    await storage.put({ key: objectKey, body: mat.bytes, contentType: "application/octet-stream" })
    const presigned = await storage.presignGet({ key: objectKey })

    // 写 eval_jobs（queued）
    await repo.create({
      jobId,
      projectId,
      orgId: tenant.orgId,
      apiKeyId: tenant.apiKeyId,
      inputKind: mat.inputKind,
      scope: mat.scope,
      inputObjectKey: objectKey,
      inputPresignedUrl: presigned.url,
      ruleSetId: input.ruleSetId,
      taskId: input.taskId ?? null,
      taskTitle: input.taskTitle ?? null,
      taskSubject: input.taskSubject ?? null,
    })

    // 触发 executor（生产 SCF；本地 TENCENT_SCF_ENABLED=false 时仅入队，由 worker 轮询）
    const cfg = getConfig()
    let scfRequestId: string | undefined
    if (cfg.scfEnabled) {
      const payload: ScfInvokePayload = {
        job_id: jobId,
        rule_set_id: input.ruleSetId,
        input_kind: mat.inputKind,
        scope: mat.scope,
        input_object_key: objectKey,
        input_presigned_url: presigned.url,
        task_id: input.taskId,
        task_title: input.taskTitle,
        task_subject: input.taskSubject,
      }
      const resp = await invokeScf(payload)
      scfRequestId = resp.RequestId
      if (scfRequestId) {
        await repo.updateScfRequestId(jobId, scfRequestId).catch(() => {
          /* best-effort：链路追踪字段，失败不影响提交 */
        })
      }
    }

    return {
      job_id: jobId,
      status: "queued",
      project_id: projectId,
      poll_url: `/api/v1/jobs/${jobId}`,
      scf_request_id: scfRequestId,
    }
  }

  async function get(jobId: string): Promise<JobDto | null> {
    const job = await repo.findById(jobId)
    return job ? serializeJob(job) : null
  }

  /** 速览（docs/arch/12 §6.6）：job 维度解析其 run，聚合成 verdict/score + 各项失败原因。 */
  async function overview(jobId: string): Promise<OverviewResult | null> {
    const job = await repo.findById(jobId)
    if (!job) return null
    const base = {
      job_id: job.id,
      run_id: job.runId,
      status: job.status,
      web_run_url: job.webRunUrl,
      error: job.error,
    }
    // 未完成（queued/running/failed）或无 run：只回状态 + 任务级 error，items 为空
    if (job.status !== "completed" || !job.runId) {
      return { ...base, items: [] }
    }
    const queryRepo = new QueryRepository(tenant)
    const run = (await queryRepo.runOverview(tenant.projectId!, job.runId)) as OverviewRun | null
    if (!run) {
      // job 已 completed 但 run 未回传/未找到：返回空 items，避免阻塞调用方
      return { ...base, items: [] }
    }
    return buildJobOverview(base, run)
  }

  return { submit, get, overview }
}
