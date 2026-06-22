/**
 * API Key HMAC 验签中间件（§6.3，Ingestion 侧鉴权）。
 *
 * 验签步骤：
 *  1. 解析 Authorization: `Eval <publicKey>:<signature>`。
 *  2. 按 publicKey 查 api_keys：存在、未吊销、未过期、scope 含 ingest。
 *  3. 解密 secret_encrypted 得 secret，重算 HMAC（METHOD\nPATH\nsha256(body)），常量时间比较。
 *  4. 通过 → 注入 req.tenant = { kind:'apikey', apiKeyId, projectId, orgId }；
 *     失败 → 401 AUTH_INVALID。
 *  5. 异步更新 last_used_at / call_count / last_ip（非阻塞）。
 *
 * 依赖 req.rawBody（原始请求体字节）——由 express.json 的 verify 钩子捕获（server.ts）。
 * body 字节必须与客户端签名所用字节严格一致。
 */

import type { RequestHandler } from "express"
import { ApiKeyRepository } from "../repositories/apiKey.repository"
import { parseAuthHeader, decryptSecret, signHmac, timingSafeEqualHex } from "../infra/crypto"
import { PlatformError } from "./errorHandler"

const repo = new ApiKeyRepository({})

function unauthorized(msg?: string): PlatformError {
  return new PlatformError(msg || "invalid api key or signature", {
    status: 401,
    code: "AUTH_INVALID",
  })
}

export const requireApiKey: RequestHandler = async (req, _res, next) => {
  try {
    const parsed = parseAuthHeader(req.get("authorization"))
    if (!parsed) return next(unauthorized())

    const key = await repo.findByPublicKey(parsed.publicKey)
    if (!key || !key.project) return next(unauthorized())
    if (key.revokedAt) return next(unauthorized("key revoked"))
    if (key.expiresAt && key.expiresAt.getTime() < Date.now()) {
      return next(unauthorized("key expired"))
    }
    if (!Array.isArray(key.scopes) || !key.scopes.includes("ingest")) {
      return next(unauthorized("scope denied"))
    }

    let secret: string
    try {
      secret = decryptSecret(key.secretEncrypted)
    } catch {
      return next(unauthorized())
    }
    const rawBody = req.rawBody || Buffer.alloc(0)
    // 用 originalUrl 取完整路径（子路由挂载时 req.path 是相对挂载点的，与客户端签名路径不一致）
    const fullPath = req.originalUrl.split("?")[0]
    const expected = signHmac(secret, req.method, fullPath, rawBody)
    if (!timingSafeEqualHex(expected, parsed.signature)) {
      return next(unauthorized("signature mismatch"))
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
