/**
 * 项目管理路由（/api/v1/projects）。
 *  - GET    /:id            详情
 *  - PATCH  /:id            更新
 *  - POST   /:id/archive    归档（owner）
 *  - POST   /:id/unarchive  恢复（owner）
 *  - DELETE /:id            永久删除（owner；级联运行/样本/制品 + 清理对象存储）
 *
 * projectGuard 解析 :id → 校验归属与成员关系 → 注入 req.tenant（含 projectId）。
 */

import { Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { PlatformError } from "../middleware/errorHandler"
import { projectGuard } from "../middleware/tenantGuard"
import { createProjectService } from "../services/project.service"
import { createQueryService } from "../services/query.service"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

router.get(
  "/:id",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!)
    res.json({ project: await svc.get(req.params.id) })
  }),
)

// ── Query：运行列表 / 趋势（§九）──
router.get(
  "/:id/runs",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const q = req.query as Record<string, string | undefined>
    const svc = createQueryService(req.tenant!)
    res.json(
      await svc.listRuns(req.params.id, {
        mode: q.mode,
        ruleSetVersion: q.rule_set_version,
        from: q.from ? new Date(q.from) : undefined,
        to: q.to ? new Date(q.to) : undefined,
        order: q.order === "asc" ? "asc" : "desc",
        page: q.page ? Number(q.page) : 1,
        size: q.size ? Number(q.size) : 50,
      }),
    )
  }),
)

router.get(
  "/:id/trends",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const q = req.query as Record<string, string | undefined>
    const svc = createQueryService(req.tenant!)
    res.json(
      await svc.trends(req.params.id, {
        from: q.from ? new Date(q.from) : undefined,
        to: q.to ? new Date(q.to) : undefined,
        limit: q.limit ? Number(q.limit) : 100,
      }),
    )
  }),
)

// ── Query：样本级走势（§14）──
router.get(
  "/:id/samples",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!)
    res.json(await svc.samples(req.params.id))
  }),
)

router.get(
  "/:id/sample-trends",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const q = req.query as Record<string, string | undefined>
    const sampleId = q.sample_id
    if (!sampleId) {
      res.status(400).json({ error: "sample_id required", code: "SCHEMA_INVALID" })
      return
    }
    const svc = createQueryService(req.tenant!)
    res.json(
      await svc.sampleTrends(req.params.id, sampleId, q.limit ? Number(q.limit) : 100),
    )
  }),
)

router.patch(
  "/:id",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!)
    res.json({ project: await svc.update(req.params.id, req.body || {}) })
  }),
)

router.post(
  "/:id/archive",
  requireAuth,
  projectGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!)
    res.json({ project: await svc.setArchived(req.params.id, true) })
  }),
)

router.post(
  "/:id/unarchive",
  requireAuth,
  projectGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!)
    res.json({ project: await svc.setArchived(req.params.id, false) })
  }),
)

router.delete(
  "/:id",
  requireAuth,
  projectGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!)
    await svc.delete(req.params.id)
    res.json({ ok: true })
  }),
)

// Webhook 测试回调（前端「发送测试回调」按钮）
router.post(
  "/:id/test-webhook",
  requireAuth,
  projectGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const { sendTestWebhook } = await import("../services/webhook.service")
    const result = await sendTestWebhook(req.params.id)
    if (!result.url) {
      throw new PlatformError("no webhook URL configured", { status: 400, code: "INPUT_INVALID" })
    }
    res.json(result)
  }),
)

// Webhook 投递历史（项目级，最近 N 条）
router.get(
  "/:id/webhook-deliveries",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const { PrismaClient } = await import("@prisma/client")
    const prisma = new PrismaClient()
    const limit = Math.min(50, parseInt(String(req.query.limit ?? "20"), 10) || 20)
    const deliveries = await prisma.webhookDelivery.findMany({
      where: { projectId: req.params.id },
      orderBy: { createdAt: "desc" },
      take: limit,
      select: {
        id: true,
        jobId: true,
        event: true,
        url: true,
        attempt: true,
        success: true,
        statusCode: true,
        error: true,
        durationMs: true,
        requestBody: true,
        responseBody: true,
        createdAt: true,
      },
    })
    await prisma.$disconnect()
    res.json({ deliveries })
  }),
)

export default router
