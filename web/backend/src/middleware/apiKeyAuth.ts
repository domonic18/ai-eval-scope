/**
 * API Key Bearer 鉴权中间件（§6.3，Ingestion 侧鉴权）。
 *
 * 验证步骤：
 *  1. 解析 Authorization: `Bearer <token>`。
 *  2. 按 sha256(token) 查 api_keys（tokenHash）：存在、未吊销、未过期、scope 含 ingest。
 *  3. 通过 → 注入 req.tenant = { kind:'apikey', apiKeyId, projectId, orgId }；
 *     失败 → 401 AUTH_INVALID。
 *  4. 异步更新 last_used_at / call_count / last_ip（非阻塞）。
 */

import type { RequestHandler } from "express"
import { ApiKeyRepository } from "../repositories/apiKey.repository"
import { parseBearerToken, hashToken } from "../infra/crypto"
import { PlatformError } from "./errorHandler"

const repo = new ApiKeyRepository({})

function unauthorized(msg?: string): PlatformError {
  return new PlatformError(msg || "invalid api key", { status: 401, code: "AUTH_INVALID" })
}

export const requireApiKey: RequestHandler = async (req, _res, next) => {
  try {
    const token = parseBearerToken(req.get("authorization"))
    if (!token) return next(unauthorized())

    const key = await repo.findByTokenHash(hashToken(token))
    if (!key || !key.project) return next(unauthorized())
    if (key.revokedAt) return next(unauthorized("key revoked"))
    if (key.expiresAt && key.expiresAt.getTime() < Date.now()) {
      return next(unauthorized("key expired"))
    }
    if (!Array.isArray(key.scopes) || !key.scopes.includes("ingest")) {
      return next(unauthorized("scope denied"))
    }

    req.tenant = {
      kind: "apikey",
      apiKeyId: key.id,
      projectId: key.project.id,
      orgId: key.project.orgId,
      scopes: key.scopes,
    }

    // 非阻塞：更新使用统计
    setImmediate(() => {
      repo.recordUsage(key.id, { ip: req.ip }).catch(() => {})
    })

    next()
  } catch (err) {
    next(err)
  }
}
