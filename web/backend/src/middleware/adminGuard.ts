/**
 * 平台超管守卫（超级管理员后台用）。
 *
 * **以 DB 为准**：重读 User.role/status，而非纯信 JWT 里的 platform_admin claim——
 * 这样降权 / 禁用能在下一次请求立即生效（不必等 token 过期）。
 * 非 admin 或 status=disabled → 403 FORBIDDEN。
 *
 * 与 tenantGuard 互斥：admin 接口跨租户，不做组织成员关系校验。
 */
import type { RequestHandler } from "express"
import { UserRepository } from "../repositories/user.repository"
import { PlatformError } from "./errorHandler"

const userRepo = new UserRepository()

export const platformAdminGuard: RequestHandler = async (req, _res, next) => {
  try {
    if (!req.user) {
      return next(new PlatformError("auth required", { status: 401, code: "AUTH_INVALID" }))
    }
    const user = await userRepo.findById(req.user.userId)
    if (!user || user.role !== "admin" || user.status !== "active") {
      return next(new PlatformError("platform admin required", { status: 403, code: "FORBIDDEN" }))
    }
    next()
  } catch (err) {
    next(err)
  }
}
