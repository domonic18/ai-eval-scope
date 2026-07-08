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
      platformAdmin: payload.platform_admin === true,
      authTime: payload.auth_time,
    }
    next()
  } catch {
    return next(
      new PlatformError("invalid or expired token", { status: 401, code: "AUTH_INVALID" }),
    )
  }
}

/**
 * 可选鉴权（docs/arch/12 §3.5 公开项目）：带有效 JWT 则注入 req.user；否则匿名继续。
 * 配合 runGuard/artifactGuard 的公开分支：匿名访问公开项目的运行/样本/制品（只读）。
 * 无效/过期 token 视为匿名（不抛 401），由后续 guard 按项目是否公开决定放行或 401。
 */
export const optionalAuth: RequestHandler = (req, _res, next) => {
  const header = req.get("authorization") || ""
  const m = header.match(/^Bearer\s+(.+)$/i)
  if (!m) return next()
  try {
    const payload = verifyToken(m[1])
    if (payload.kind !== "access") return next()
    req.user = {
      userId: payload.sub,
      orgId: payload.org_id || null,
      role: payload.role || null,
      platformAdmin: payload.platform_admin === true,
      authTime: payload.auth_time,
    }
  } catch {
    /* 无效 token：匿名继续 */
  }
  next()
}
