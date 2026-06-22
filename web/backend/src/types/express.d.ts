/**
 * Express Request 类型增强：注入认证/租户/原始请求体字段，
 * 消除中间件与路由里 req.user / req.tenant / req.rawBody 的隐式 any。
 */
import type { Tenant } from "../repositories/base.repository"

declare module "express-serve-static-core" {
  interface Request {
    user?: {
      userId: string
      orgId: string | null
      role: string | null
      authTime?: number
    }
    tenant?: Tenant
    rawBody?: Buffer
  }
}

export {}
