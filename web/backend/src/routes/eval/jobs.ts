/**
 * 评测任务路由（/api/v1/jobs）—— 合并自 eval-gateway。
 *  - POST /          提交评估（octet-stream 原始字节 + 查询串元数据 / application/json 内联）
 *  - GET  /:jobId    查询任务态
 *
 * 鉴权：requireApiKey（Bearer API Key，scope=ingest）。项目归属由 Key 决定。
 *
 * 输入约定（对齐调试台）：application/octet-stream + 查询串 ?filename=&rule_set_id=…，
 * 避开 multipart 解析依赖；application/json 走全局 json parser（{content:{filename,text}}）。
 */

import { raw, Router, type RequestHandler } from "express"
import crypto from "crypto"
import { requireApiKey } from "../../middleware/apiKeyAuth"
import { PlatformError } from "../../middleware/errorHandler"
import { rateLimiter } from "../../middleware/rateLimiter"
import { createEvalJobService } from "../../services/evalJob.service"
import { notifyJobCompletion } from "../../services/webhook.service"
import { getLogger } from "../../infra/logger"
import { getObjectStorage } from "../../infra/objectStorage"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

router.post(
  "/",
  requireApiKey,
  rateLimiter(), // 按 API Key 令牌桶限流；超限 429 RATE_LIMITED + Retry-After
  // octet-stream 原始 body（仅本路由生效，不动全局 json parser）
  raw({ type: ["application/octet-stream", "text/plain"], limit: "50mb" }),
  wrap(async (req, res) => {
    const svc = createEvalJobService(req.tenant!)
    const ct = req.get("content-type") || ""
    const q = req.query as Record<string, string | undefined>

    if (ct.includes("application/json")) {
      const body = (req.body || {}) as {
        content?: { filename?: string; text?: string }
        input_object_key?: string
        rule_set_id?: string
        package_id?: string // Phase 3：rule_set_id 的 package 语义别名（优先）
        package_ref?: string // S2-D：场景包引用 scenario/package:label（调用方须显式提供）
        task_id?: string
        task_title?: string
        task_subject?: string
      }
      const result = await svc.submit({
        inlineFilename: body.content?.filename,
        inlineText: body.content?.text,
        inputObjectKey: body.input_object_key,
        ruleSetId: body.package_id || body.rule_set_id || "",
        packageRef: body.package_ref,
        taskId: q.task_id || body.task_id,
        taskTitle: q.task_title || body.task_title,
        taskSubject: q.task_subject || body.task_subject,
      })
      return res.status(202).json(result)
    }

    const filename = q.filename
    if (!filename) {
      throw new PlatformError("filename is required (query)", { status: 400, code: "INPUT_INVALID" })
    }
    const fileBytes = req.body as Buffer
    if (!Buffer.isBuffer(fileBytes) || fileBytes.length === 0) {
      throw new PlatformError("file body is empty", { status: 400, code: "INPUT_INVALID" })
    }

    const result = await svc.submit({
      filename,
      fileBytes,
      ruleSetId: q.package_id || q.rule_set_id || "",
      packageRef: q.package_ref,
      taskId: q.task_id,
      taskTitle: q.task_title,
      taskSubject: q.task_subject,
    })
    res.status(202).json(result)
  }),
)

// 签发 presigned PUT URL —— 大文件客户端直传对象存储后，用 input_object_key 提交评测
router.post(
  "/request-upload",
  requireApiKey,
  wrap(async (req, res) => {
    const projectId = req.tenant!.projectId!
    const body = (req.body || {}) as {
      filename?: string
      content_type?: string
    }
    const filename = body.filename
    if (!filename) {
      throw new PlatformError("filename is required", {
        status: 400,
        code: "INPUT_INVALID",
      })
    }
    const ext = (filename.match(/\.[^.]+$/) || [".md"])[0]
    const objectKey = `projects/${projectId}/eval/jobs/uploads/${crypto.randomUUID()}/input${ext}`
    const presigned = await getObjectStorage().presignPut({
      key: objectKey,
      contentType: body.content_type || "application/octet-stream",
    })
    res.status(200).json({
      upload_url: presigned.url,
      object_key: objectKey,
      expires_at: presigned.expiresAt,
    })
  }),
)

router.get(
  "/:jobId",
  requireApiKey,
  wrap(async (req, res) => {
    const svc = createEvalJobService(req.tenant!)
    const job = await svc.get(req.params.jobId)
    if (!job) {
      throw new PlatformError("job not found", { status: 404, code: "JOB_NOT_FOUND" })
    }
    res.json(job)
  }),
)

// 速览：过没过 / 分数 + 各评测项得分与失败原因（docs/arch/12 §6.6）。深度详情走 iframe。
router.get(
  "/:jobId/overview",
  requireApiKey,
  wrap(async (req, res) => {
    const svc = createEvalJobService(req.tenant!)
    const overview = await svc.overview(req.params.jobId)
    if (!overview) {
      throw new PlatformError("job not found", { status: 404, code: "JOB_NOT_FOUND" })
    }
    res.json(overview)
  }),
)

// executor 领取任务后重签输入下载 URL（提交时签发的 presigned URL ≤15min，排队积压会拖过期）
router.get(
  "/:jobId/input-url",
  requireApiKey,
  wrap(async (req, res) => {
    const svc = createEvalJobService(req.tenant!)
    const r = await svc.refreshInputUrl(req.params.jobId)
    if (!r) {
      throw new PlatformError("job not found", { status: 404, code: "JOB_NOT_FOUND" })
    }
    res.json(r)
  }),
)

// executor 完成 job 后通知 web → web 异步投递 webhook 回调（fire-and-forget，不阻塞响应）
router.post(
  "/:jobId/notify-completion",
  requireApiKey,
  wrap(async (req, res) => {
    notifyJobCompletion(req.params.jobId).catch((e) =>
      getLogger().warn({ jobId: req.params.jobId, error: String(e) }, "webhook.notify_failed"),
    )
    res.status(202).json({ notified: true })
  }),
)

export default router
