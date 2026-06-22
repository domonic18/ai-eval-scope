/**
 * JWT 鉴权中间件（§6.2）。
 * 解析 Bearer access_token → 校验 → 注入 req.user = { userId, orgId, role }。
 */

import type { RequestHandler } from "express"
import { verifyToken } from "../infra/crypto"
import { PlatformError } from "./errorHandler"

export const requireAuth: RequestHandler = (req, _res, next) => {
  const header = req.get("authorization") || ""
  const m = header.match(/^Bearer\s+(.+)$/i)
  if (!m) {
    return next(new PlatformError("missing access token", { status: 401, code: "AUTH_INVALID" }))
  }
  try {
    const payload = verifyToken(m[1])
    if (payload.kind !== "access") {
      return next(new PlatformError("wrong token kind", { status: 401, code: "AUTH_INVALID" }))
    }
    req.user = {
      userId: payload.sub,
      orgId: payload.org_id || null,
      role: payload.role || null,
      authTime: payload.auth_time,
    }
    next()
  } catch {
    return next(
      new PlatformError("invalid or expired token", { status: 401, code: "AUTH_INVALID" }),
    )
  }
}
