/**
 * 运行详情路由（/api/v1/runs）。
 *  - GET    /:id               运行详情（含样本摘要）
 *  - GET    /:id/samples/:sid  样本详情（约束 + 制品引用）
 *  - DELETE /:id               删除运行（owner；级联样本/约束/制品 + 清理对象存储文件）
 *
 * runGuard 解析 :id(run)→project→org→成员关系，注入 req.tenant（含 projectId）。
 */

import { Router, type RequestHandler } from "express"
import { requireAuth, optionalAuth } from "../middleware/auth"
import { runGuard } from "../middleware/tenantGuard"
import { createQueryService } from "../services/query.service"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

// GET 用 optionalAuth：公开项目的运行/样本详情免登录可读（iframe 嵌入，docs/arch/12 §3.5）。
// DELETE 仍 requireAuth + owner（写操作不开放匿名）。
router.get(
  "/:id",
  optionalAuth,
  runGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!)
    res.json({ run: await svc.runDetail(req.tenant!.projectId!, req.params.id) })
  }),
)

router.get(
  "/:id/samples/:sid",
  optionalAuth,
  runGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!)
    res.json({ sample: await svc.sampleDetail(req.tenant!.projectId!, req.params.sid) })
  }),
)

// Phase 5：运行配置快照（metricDefinitions / aggregationPolicy，前端动态渲染用）
router.get(
  "/:id/snapshot",
  optionalAuth,
  runGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!)
    res.json({ snapshot: await svc.runSnapshot(req.tenant!.projectId!, req.params.id) })
  }),
)

router.delete(
  "/:id",
  requireAuth,
  runGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!)
    await svc.deleteRun(req.params.id)
    res.json({ ok: true })
  }),
)

export default router
