/**
 * API Key 管理路由（/api/v1/projects/:id/keys）。
 *  - GET  /           列表（不含 secret）
 *  - POST /           签发（secret 明文仅本次返回）
 *  - POST /:keyId/revoke  吊销
 *
 * projectGuard 注入 req.tenant（含 projectId + orgId）。mergeParams 保留 :id。
 */

import { Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { projectGuard } from "../middleware/tenantGuard"
import { createApiKeyService } from "../services/apiKey.service"

const router = Router({ mergeParams: true })

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

router.get(
  "/",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const svc = createApiKeyService(req.tenant!)
    res.json({ keys: await svc.list(req.params.id) })
  }),
)

router.post(
  "/",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const svc = createApiKeyService(req.tenant!)
    const key = await svc.issue(req.params.id, req.body || {})
    res.status(201).json({ key })
  }),
)

router.post(
  "/:keyId/revoke",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const svc = createApiKeyService(req.tenant!)
    res.json({ key: await svc.revoke(req.params.id, req.params.keyId) })
  }),
)

export default router
