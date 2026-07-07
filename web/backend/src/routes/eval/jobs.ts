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
import { requireApiKey } from "../../middleware/apiKeyAuth"
import { PlatformError } from "../../middleware/errorHandler"
import { createEvalJobService } from "../../services/evalJob.service"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

const DEFAULT_RULE_SET = "coursework-quality"

router.post(
  "/",
  requireApiKey,
  // octet-stream 原始 body（仅本路由生效，不动全局 json parser）
  raw({ type: ["application/octet-stream", "text/plain"], limit: "50mb" }),
  wrap(async (req, res) => {
    const svc = createEvalJobService(req.tenant!)
    const ct = req.get("content-type") || ""
    const q = req.query as Record<string, string | undefined>

    if (ct.includes("application/json")) {
      const body = (req.body || {}) as {
        content?: { filename?: string; text?: string }
        rule_set_id?: string
        task_id?: string
        task_title?: string
        task_subject?: string
      }
      const result = await svc.submit({
        inlineFilename: body.content?.filename,
        inlineText: body.content?.text,
        ruleSetId: body.rule_set_id || DEFAULT_RULE_SET,
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
      ruleSetId: q.rule_set_id || DEFAULT_RULE_SET,
      taskId: q.task_id,
      taskTitle: q.task_title,
      taskSubject: q.task_subject,
    })
    res.status(202).json(result)
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

export default router
