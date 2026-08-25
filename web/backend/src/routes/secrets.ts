/**
 * 平台 Secrets 管理路由（org 级，W3，arch/16 §2.4）。
 *  - GET    /orgs/:org/secrets            列表（member 可见；名称+时间，值不可读）
 *  - PUT    /orgs/:org/secrets/:name      新增/覆盖（owner；body {value}）
 *  - DELETE /orgs/:org/secrets/:name      删除（owner）
 */

import { Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { orgGuard } from "../middleware/tenantGuard"
import { createSecretsService } from "../services/secrets.service"

const router = Router({ mergeParams: true })

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

router.get(
  "/orgs/:org/secrets",
  requireAuth,
  orgGuard(),
  wrap(async (req, res) => {
    const svc = createSecretsService(req.tenant!.orgId!)
    res.json({ secrets: await svc.list() })
  }),
)

router.put(
  "/orgs/:org/secrets/:name",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createSecretsService(req.tenant!.orgId!)
    const { value } = (req.body ?? {}) as { value?: string }
    const view = await svc.upsert(req.params.name, String(value ?? ""), req.user!.userId)
    res.json(view) // 只回 name+时间，值不回显
  }),
)

router.delete(
  "/orgs/:org/secrets/:name",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createSecretsService(req.tenant!.orgId!)
    await svc.remove(req.params.name)
    res.status(204).end()
  }),
)

export default router
