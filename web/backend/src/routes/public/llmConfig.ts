/**
 * 执行面 LLM 配置拉取路由（/api/public/llm-config，Bearer API Key 鉴权）。
 *
 * executor（云函数）启动时拉取角色注册表（arch/16 §6.2-四 云端形态）：
 *   GET /api/public/llm-config → { roles: { text: {provider, model, api_key(解密), ...}, vision: {...} } }
 * 与 CLI 形态（~/.agent_eval/llm.json）互不感知；云函数不读任何本地文件。
 * 每次拉取打审计日志（角色与 actor，不含密钥）；明文仅出现在鉴权后的 HTTPS 响应中。
 */

import { Router, type RequestHandler } from "express"
import { requireApiKey } from "../../middleware/apiKeyAuth"
import { rateLimiter } from "../../middleware/rateLimiter"
import { llmClientService } from "../../services/llm-client.service"

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
    const payload = await llmClientService.resolveForExecutor(`apikey:${tenant.apiKeyId}`)
    res.json(payload)
  }),
)

export default router
