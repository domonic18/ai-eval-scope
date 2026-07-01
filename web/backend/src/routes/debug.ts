/**
 * 调试台路由（/api/v1/projects/:id/debug）—— owner 专属，把评估请求转发给 eval-gateway。
 *  - POST /jobs          提交评估（原始文件字节 + 查询串元数据）→ gateway multipart 上传
 *  - GET  /jobs/:jobId   查询任务态（透传 gateway JobResponse）
 *
 * 鉴权：projectGuard({ role: "owner" }) —— 仅目标项目的组织 owner 可用（普通 member 403）。
 * 凭据：以该项目 API Key（Bearer token）转发 gateway；token 来自请求 api_key 或项目首个未吊销 Key。
 */

import { raw, Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { projectGuard } from "../middleware/tenantGuard"
import { PlatformError } from "../middleware/errorHandler"
import { getConfig } from "../config"
import { decryptToken } from "../infra/crypto"
import { getJob, submitJob } from "../infra/gatewayClient"
import { ApiKeyRepository } from "../repositories/apiKey.repository"
import { AuditService } from "../services/audit.service"
import { getLogger } from "../infra/logger"

const router = Router({ mergeParams: true })

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

/** 取项目首个未吊销 API Key 的 token 明文；无可用 key → 抛 400。 */
async function pickProjectKey(projectId: string, orgId: string): Promise<string> {
  const repo = new ApiKeyRepository({ kind: "user", orgId, projectId, role: "owner" })
  const keys = await repo.listByProject(projectId)
  const key = keys.find((k) => k.revokedAt === null)
  if (!key) {
    throw new PlatformError("该项目尚无可用 API Key，请先在项目设置创建", {
      status: 400,
      code: "NO_API_KEY",
    })
  }
  return decryptToken(key.tokenEncrypted)
}

/** token 脱敏：eval-xxxx…yyyy（调试台展示用，不回显完整 token）。 */
function maskToken(token: string): string {
  return token.length > 16 ? `${token.slice(0, 12)}…${token.slice(-4)}` : "***"
}

// 入参用 application/octet-stream（原始文件字节）+ 查询串元数据，避开 multipart 解析依赖
router.post(
  "/jobs",
  requireAuth,
  projectGuard({ role: "owner" }),
  // 原始 body 解析：仅本路由生效，不动全局 json parser
  raw({ type: "application/octet-stream", limit: "50mb" }),
  wrap(async (req, res) => {
    const tenant = req.tenant!
    const projectId = tenant.projectId!
    const q = req.query as Record<string, string | undefined>
    const filename = q.filename
    if (!filename) {
      throw new PlatformError("filename is required (query)", { status: 400, code: "INPUT_INVALID" })
    }
    const fileBytes = req.body as Buffer
    if (!Buffer.isBuffer(fileBytes) || fileBytes.length === 0) {
      throw new PlatformError("file body is empty", { status: 400, code: "INPUT_INVALID" })
    }
    const ruleSetId = q.rule_set_id || "coursework-default"
    // 可选任务字段：不填则 gateway 回退（单页 sample_id 恒为 contents）
    const taskId = q.task_id?.trim() || undefined
    const taskTitle = q.task_title?.trim() || undefined
    const taskSubject = q.task_subject?.trim() || undefined

    const apiKey = q.api_key?.trim()
    const token = apiKey || (await pickProjectKey(projectId, tenant.orgId!))
    const baseUrl = getConfig().gatewayBaseUrl
    const result = await submitJob({
      baseUrl,
      token,
      filename,
      fileBytes,
      ruleSetId,
      taskId,
      taskTitle,
      taskSubject,
    })

    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "debug.job.submit",
      targetType: "project",
      targetId: projectId,
      metadata: { jobId: result.job_id, filename, ruleSetId, taskId },
    }).catch((e) => getLogger().warn({ error: (e as Error).message }, "audit_log_failed"))

    res.status(202).json({
      ...result,
      debug: {
        request: {
          method: "POST",
          url: `${baseUrl}/v1/jobs`,
          headers: {
            Authorization: `Bearer ${maskToken(token)}`,
            "Content-Type": "multipart/form-data; boundary=<auto>",
          },
          body: {
            file: { filename, sizeBytes: fileBytes.length },
            fields: {
              rule_set_id: ruleSetId,
              ...(taskId ? { task_id: taskId } : {}),
              ...(taskTitle ? { task_title: taskTitle } : {}),
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
  projectGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const tenant = req.tenant!
    const apiKey = (req.query as Record<string, string | undefined>).api_key?.trim()
    const token = apiKey || (await pickProjectKey(tenant.projectId!, tenant.orgId!))
    const job = await getJob(getConfig().gatewayBaseUrl, token, req.params.jobId)
    res.json(job)
  }),
)

export default router
