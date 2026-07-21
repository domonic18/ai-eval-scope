/**
 * 调试台路由（/api/v1/debug）—— SSO 登录用户共享的评估沙盒。
 *  - POST /jobs          提交评估（原始文件字节 + 查询串元数据）→ evalJobService（合并自 gateway）
 *  - GET  /jobs/:jobId   查询任务态
 *  - GET  /rule-sets     规则集目录（静态 catalog）
 *
 * 鉴权：requireAuth（SSO 登录，作为审计 actor）+ 必填 api_key（query，明文 Bearer token）。
 *   - 授权 = 持有一把有效 API Key；结果按 Key 归属落到对应项目。
 *   - api_key 必填：任何登录用户必须自带 Key，绝不能"留空则取项目库里的 Key"（否则越权）。
 *   - 不再转发 gateway：直接在 Web 进程内调用 evalJobService（提交后由 executor 执行）。
 */

import { raw, Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { PlatformError } from "../middleware/errorHandler"
import { hashToken } from "../infra/crypto"
import { readRuleSetsCatalog } from "../infra/ruleSetsCatalog"
import { getLogger } from "../infra/logger"
import { ApiKeyRepository } from "../repositories/apiKey.repository"
import type { Tenant } from "../repositories/base.repository"
import { createEvalJobService } from "../services/evalJob.service"
import { AuditService } from "../services/audit.service"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

/** 从查询串取必填 api_key（明文 Bearer token）；缺失 → 抛 400。 */
function requireApiKey(req: Parameters<RequestHandler>[0]): string {
  const token = (req.query as Record<string, string | undefined>).api_key?.trim()
  if (!token) {
    throw new PlatformError("api_key is required (query)", { status: 400, code: "INPUT_INVALID" })
  }
  return token
}

/** token 脱敏：eval-xxxx…yyyy（调试台展示用，不回显完整 token）。 */
function maskToken(token: string): string {
  return token.length > 16 ? `${token.slice(0, 12)}…${token.slice(-4)}` : "***"
}

/** 由明文 token 解析 tenant（复用鉴权逻辑，调试台从 query 而非 Bearer 头取 token）。 */
async function resolveTenant(token: string): Promise<Tenant> {
  const repo = new ApiKeyRepository()
  const key = await repo.findByTokenHash(hashToken(token))
  if (!key || !key.project) {
    throw new PlatformError("invalid api key", { status: 401, code: "AUTH_INVALID" })
  }
  if (key.revokedAt) {
    throw new PlatformError("key revoked", { status: 401, code: "AUTH_INVALID" })
  }
  if (key.expiresAt && key.expiresAt.getTime() < Date.now()) {
    throw new PlatformError("key expired", { status: 401, code: "AUTH_INVALID" })
  }
  return {
    kind: "apikey",
    apiKeyId: key.id,
    projectId: key.project.id,
    orgId: key.project.orgId,
    scopes: key.scopes,
  }
}

// 入参用 application/octet-stream（原始文件字节）+ 查询串元数据，避开 multipart 解析依赖
router.post(
  "/jobs",
  requireAuth,
  raw({ type: "application/octet-stream", limit: "50mb" }),
  wrap(async (req, res) => {
    const q = req.query as Record<string, string | undefined>
    const filename = q.filename
    if (!filename) {
      throw new PlatformError("filename is required (query)", { status: 400, code: "INPUT_INVALID" })
    }
    const fileBytes = req.body as Buffer
    if (!Buffer.isBuffer(fileBytes) || fileBytes.length === 0) {
      throw new PlatformError("file body is empty", { status: 400, code: "INPUT_INVALID" })
    }
    const ruleSetId = q.rule_set_id || "coursework-quality"
    const taskId = q.task_id?.trim() || undefined
    const taskTitle = q.task_title?.trim() || undefined
    const taskSubject = q.task_subject?.trim() || undefined

    const token = requireApiKey(req)
    const tenant = await resolveTenant(token)
    const svc = createEvalJobService(tenant)
    const result = await svc.submit({
      filename,
      fileBytes,
      ruleSetId,
      taskId,
      taskTitle,
      taskSubject,
    })

    await AuditService.log({
      // 归属由 API Key 验签解析
      orgId: tenant.orgId ?? null,
      actorUserId: req.user!.userId,
      action: "debug.job.submit",
      targetType: "project",
      targetId: tenant.projectId ?? null,
      metadata: { job_id: result.job_id, filename, ruleSetId, taskId },
    }).catch((e) => getLogger().warn({ error: (e as Error).message }, "audit_log_failed"))

    res.status(202).json({
      ...result,
      debug: {
        request: {
          method: "POST",
          url: "/api/v1/jobs",
          headers: {
            Authorization: `Bearer ${maskToken(token)}`,
            "Content-Type": "application/octet-stream",
          },
          body: {
            file: { filename, sizeBytes: fileBytes.length },
            fields: {
              rule_set_id: ruleSetId,
              ...(taskId ? { task_id: taskId } : {}),
            },
          },
        },
        response: { status: 202, body: result },
      },
    })
  }),
)

router.get(
  "/jobs/:jobId",
  requireAuth,
  wrap(async (req, res) => {
    const token = requireApiKey(req)
    const tenant = await resolveTenant(token)
    const svc = createEvalJobService(tenant)
    const job = await svc.get(req.params.jobId)
    if (!job) {
      throw new PlatformError("job not found", { status: 404, code: "JOB_NOT_FOUND" })
    }
    res.json(job)
  }),
)

// 速览（overview）：与第三方 /jobs/:jobId/overview 同结构，方便 /debug 页面调试
router.get(
  "/jobs/:jobId/overview",
  requireAuth,
  wrap(async (req, res) => {
    const token = requireApiKey(req)
    const tenant = await resolveTenant(token)
    const svc = createEvalJobService(tenant)
    const overview = await svc.overview(req.params.jobId)
    if (!overview) {
      throw new PlatformError("job not found", { status: 404, code: "JOB_NOT_FOUND" })
    }
    res.json(overview)
  }),
)

// 规则集目录（静态 catalog，与 /api/v1/rule-sets 同源）；登录即可读
router.get(
  "/rule-sets",
  requireAuth,
  wrap(async (_req, res) => {
    res.json({ rule_sets: readRuleSetsCatalog() })
  }),
)

export default router
