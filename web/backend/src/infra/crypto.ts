/**
 * 加密原语（§六 认证与多租户）。
 *
 * - 密码：argon2id 哈希（验证标准要求）。
 * - JWT：单一长效 access token（含 userId/orgId/role）。无 refresh；过期即重登。
 * - API Key：单一 Bearer token（eval-<hex>）；服务端存「加密态」（AES-256-GCM，executor 回传解密用）+「哈希态」（sha256，鉴权查找/审计/不回显）。
 */

import crypto from "crypto"
import argon2 from "argon2"
import jwt from "jsonwebtoken"
import { getConfig } from "../config"

/* ── 密码 ───────────────────────────────────────────── */
export async function hashPassword(plain: string): Promise<string> {
  return argon2.hash(plain, {
    type: argon2.argon2id,
    memoryCost: 19456, // 19 MiB
    timeCost: 2,
    parallelism: 1,
  })
}

export async function verifyPassword(plain: string, hash: string): Promise<boolean> {
  if (!hash) return false
  try {
    return await argon2.verify(hash, plain)
  } catch {
    return false
  }
}

/* ── JWT ────────────────────────────────────────────── */
// 单一长效 access token（对齐简化鉴权模型）：会话内不依赖静默 refresh，
// 避免 SCF 冷启动下 refresh 链路偶发失败导致掉登录。无 refresh token，过期即重登。
export const ACCESS_TTL_SEC = 60 * 60 * 24 * 7 // 7 days

export interface TokenPayloadInput {
  userId: string
  orgId?: string | null
  role?: string | null
  name?: string | null
  platformAdmin?: boolean
}

export interface TokenClaims extends jwt.JwtPayload {
  kind: "access"
  sub: string
  org_id: string | null
  role: string | null
  name: string | null
  platform_admin: boolean
  auth_time: number
}

function issueAccessToken(payload: TokenPayloadInput): string {
  const cfg = getConfig()
  return jwt.sign(
    {
      kind: "access",
      sub: payload.userId,
      org_id: payload.orgId || null,
      role: payload.role || null,
      name: payload.name || null,
      platform_admin: payload.platformAdmin === true,
      auth_time: Math.floor(Date.now() / 1000),
    },
    cfg.jwtSecret,
    { expiresIn: ACCESS_TTL_SEC, algorithm: "HS256" },
  )
}

export interface AccessToken {
  access_token: string
  expires_in: number
}

export function issueAccessTokenResult(payload: TokenPayloadInput): AccessToken {
  return {
    access_token: issueAccessToken(payload),
    expires_in: ACCESS_TTL_SEC,
  }
}

export function verifyToken(token: string): TokenClaims {
  const cfg = getConfig()
  return jwt.verify(token, cfg.jwtSecret, { algorithms: ["HS256"] }) as TokenClaims
}

/* ── 制品预览专用 token（raw 代理鉴权）───────────────── */
/**
 * 同源流式代理 GET /artifacts/:id/raw 的鉴权凭证。
 * iframe 导航不带 Authorization，无法复用 requireAuth；改由 preview 端点
 * （已做 artifactGuard 归属校验）签发本 token 放入 URL query，raw 端点验签即放行。
 * claims 自含 objectKey，raw 端点不查 DB；短 TTL 限制爆炸半径。
 */
export const ARTIFACT_TOKEN_TTL_SEC = 60 * 5

export interface ArtifactTokenClaims extends jwt.JwtPayload {
  kind: "artifact"
  aid: string // artifactId
  key: string // objectKey（raw 端点据此拉取对象）
  ct: string // contentType（决定响应 Content-Type）
  name: string // filename
}

export function issueArtifactToken(p: {
  artifactId: string
  objectKey: string
  contentType: string
  filename: string
}): string {
  const cfg = getConfig()
  return jwt.sign(
    { kind: "artifact", aid: p.artifactId, key: p.objectKey, ct: p.contentType, name: p.filename },
    cfg.jwtSecret,
    { expiresIn: ARTIFACT_TOKEN_TTL_SEC, algorithm: "HS256" },
  )
}

export function verifyArtifactToken(token: string): ArtifactTokenClaims {
  const cfg = getConfig()
  const claims = jwt.verify(token, cfg.jwtSecret, { algorithms: ["HS256"] }) as ArtifactTokenClaims
  if (claims.kind !== "artifact") {
    throw new Error("wrong token kind")
  }
  return claims
}

/* ── API Key（单一 Bearer token）────────────────────── */
function randomToken(bytes: number): string {
  return crypto.randomBytes(bytes).toString("hex")
}

/** 生成单一 API Key（明文仅本次返回给客户端；格式 eval-<48hex>）。 */
export function generateApiKey(): string {
  return `eval-${randomToken(24)}` // 48 hex
}

/* ── token 存储态（方案 A）─────────────────────────── */
function deriveAesKey(): Buffer {
  const cfg = getConfig()
  return crypto.createHash("sha256").update(cfg.keyEncryptionKey).digest()
}

/** 加密 token 明文 → "v1:<iv_b64>:<ct_b64>:<tag_b64>"（executor 回传时解密）。 */
export function encryptToken(plain: string): string {
  const key = deriveAesKey()
  const iv = crypto.randomBytes(12)
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv)
  const ct = Buffer.concat([cipher.update(plain, "utf8"), cipher.final()])
  const tag = cipher.getAuthTag()
  return ["v1", iv.toString("base64"), ct.toString("base64"), tag.toString("base64")].join(":")
}

/** 解密 → token 明文。 */
export function decryptToken(serialized: string): string {
  const parts = String(serialized).split(":")
  if (parts.length !== 4 || parts[0] !== "v1") {
    throw new Error("invalid token ciphertext")
  }
  const [, ivB64, ctB64, tagB64] = parts
  const key = deriveAesKey()
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(ivB64, "base64"))
  decipher.setAuthTag(Buffer.from(tagB64, "base64"))
  const pt = Buffer.concat([decipher.update(Buffer.from(ctB64, "base64")), decipher.final()])
  return pt.toString("utf8")
}

/** token 的 sha256 哈希（hex）——鉴权查找用。 */
export function hashToken(plain: string): string {
  return crypto.createHash("sha256").update(plain).digest("hex")
}

/* ── Bearer 鉴权头解析 ─────────────────────────────── */
/** 解析 `Authorization: Bearer <token>` → token | null。 */
export function parseBearerToken(header?: string): string | null {
  if (!header || typeof header !== "string") return null
  const m = header.match(/^Bearer\s+(.+)$/i)
  return m ? m[1].trim() : null
}
