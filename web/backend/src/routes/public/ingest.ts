/**
 * 摄取路由（/api/public/ingest，HMAC 鉴权 + 限流）。
 *
 * 鉴权 → 限流（按 apiKey）→ 体积/批量上限 → ingest() → 映射 outcome 到 HTTP。
 */

import { Router, type RequestHandler } from "express"
import { requireApiKey } from "../../middleware/apiKeyAuth"
import { rateLimiter } from "../../middleware/rateLimiter"
import { ingest } from "../../services/ingest.service"
import { getConfig } from "../../config"
import { SUPPORTED_SCHEMA_VERSION } from "../../schemas/validate"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

router.post(
  "/",
  requireApiKey,
  rateLimiter(),
  wrap(async (req, res) => {
    const cfg = getConfig()

    // 体积上限（PAYLOAD_TOO_LARGE）
    if (req.rawBody && req.rawBody.length > cfg.ingestMaxBytes) {
      return res.status(413).json({ error: "payload too large", code: "PAYLOAD_TOO_LARGE" })
    }
    // 批量上限（不静默截断）
    const events = (req.body as { events?: unknown[] })?.events
    if (Array.isArray(events) && events.length > cfg.ingestMaxBatch) {
      return res.status(413).json({
        error: "payload too large",
        code: "PAYLOAD_TOO_LARGE",
        hint: `max ${cfg.ingestMaxBatch} events per batch; split and resend`,
      })
    }

    const outcome = await ingest(req.tenant!, req.body)

    switch (outcome.status) {
      case "accepted":
        return res.status(202).json(outcome.result)
      case "version_unsupported":
        return res.status(400).json({
          error: "unsupported schema_version",
          code: "SCHEMA_VERSION_UNSUPPORTED",
          supported: SUPPORTED_SCHEMA_VERSION,
          got: outcome.got,
        })
      case "forbidden":
        return res.status(403).json({ error: "project forbidden", code: "PROJECT_FORBIDDEN" })
      case "schema_invalid":
        return res.status(400).json({
          error: "schema invalid",
          code: "SCHEMA_INVALID",
          problems: outcome.problems,
        })
    }
  }),
)

export default router
