/**
 * 执行面 Secrets 拉取路由（/api/public/secrets，Bearer API Key 鉴权，W3/W4）。
 *
 * executor 启动时拉取 org 全量 Secrets → 注入进程 env（CredentialStore 的
 * env 通道零改动读到）。审计打点不含值；解密失败的单项跳过并告警。
 */

import { Router, type RequestHandler } from "express"
import { requireApiKey } from "../../middleware/apiKeyAuth"
import { rateLimiter } from "../../middleware/rateLimiter"
import { createSecretsService } from "../../services/secrets.service"

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
    const svc = createSecretsService(tenant.orgId!)
    const secrets = await svc.resolveForExecutor(`apikey:${tenant.apiKeyId}`)
    res.json({ secrets })
  }),
)

export default router
