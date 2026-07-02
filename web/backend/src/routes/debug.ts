/**
 * 调试台路由（/api/v1/debug）—— SSO 登录用户共享的评估沙盒，把请求转发给 eval-gateway。
 *  - POST /jobs          提交评估（原始文件字节 + 查询串元数据）→ gateway multipart 上传
 *  - GET  /jobs/:jobId   查询任务态（透传 gateway JobResponse）
 *
 * 鉴权：requireAuth（仅需 SSO 登录，作为审计 actor）+ 必填 api_key。
 *   - 授权 = 持有一把有效 API Key，由 gateway 验签；结果按 Key 归属落到对应项目。
 *   - api_key 必填：任何登录用户必须自带 Key，绝不能"留空则取项目库里的 Key"（否则
 *     只要知道项目 UUID 就能借用该项目的 Key = 越权）。
 *   - 不再接收 project_id：项目归属完全由 API Key 决定，gateway 在 202 响应里回传
 *     project_id/org_id，本路由据此落审计。
 */

import { raw, Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { PlatformError } from "../middleware/errorHandler"
import { getConfig } from "../config"
import { getJob, submitJob } from "../infra/gatewayClient"
import { AuditService } from "../services/audit.service"
import { getLogger } from "../infra/logger"

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

// 入参用 application/octet-stream（原始文件字节）+ 查询串元数据，避开 multipart 解析依赖
router.post(
  "/jobs",
  requireAuth,
  // 原始 body 解析：仅本路由生效，不动全局 json parser
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
    const ruleSetId = q.rule_set_id || "coursework-default"
    // 可选任务字段：不填则 gateway 回退（单页 sample_id 恒为 contents）
    const taskId = q.task_id?.trim() || undefined
    const taskTitle = q.task_title?.trim() || undefined
    const taskSubject = q.task_subject?.trim() || undefined

    const token = requireApiKey(req)
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
      // 归属由 API Key 验签解析（gateway 202 回传），而非调用方传入
      orgId: result.org_id ?? null,
      actorUserId: req.user!.userId,
      action: "debug.job.submit",
      targetType: "project",
      targetId: result.project_id ?? null,
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
  wrap(async (req, res) => {
    const token = requireApiKey(req)
    const job = await getJob(getConfig().gatewayBaseUrl, token, req.params.jobId)
    res.json(job)
  }),
)

export default router
