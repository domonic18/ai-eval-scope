/**
 * CLI 身份探测路由（/api/public/whoami，Bearer API Key 鉴权）。
 *
 * 供 evaluator `auth login/status` 做 Key 有效性探测与身份回执（docs/arch/15 §5.1）：
 * 200 → { kind, key, project, org }；401 AUTH_INVALID → Key 无效/吊销/过期。
 */

import { Router, type RequestHandler } from "express"
import { requireApiKey } from "../../middleware/apiKeyAuth"
import { rateLimiter } from "../../middleware/rateLimiter"
import { PlatformError } from "../../middleware/errorHandler"
import { ApiKeyRepository } from "../../repositories/apiKey.repository"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

router.get(
  "/",
  requireApiKey,
  rateLimiter(),
  wrap(async (req, res) => {
    const tenant = req.tenant!
    const identity = await new ApiKeyRepository({}).findIdentityById(tenant.apiKeyId!)
    if (!identity || identity.revokedAt) {
      // 鉴权已过但 Key 在会话中途被吊销/删除的极端态，按无效处理
      throw new PlatformError("key not found", { status: 401, code: "AUTH_INVALID" })
    }
    const { org, ...project } = identity.project
    res.json({
      kind: "apikey",
      key: { id: identity.id, name: identity.name, scopes: identity.scopes },
      project,
      org,
    })
  }),
)

export default router
