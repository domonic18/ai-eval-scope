/**
 * 加密原语（§六 认证与多租户）。
 *
 * - 密码：argon2id 哈希（验证标准要求）。
 * - JWT：access（短期，含 userId/orgId/role）+ refresh（长期）。
 * - API Key：pk-eval-<hex> / sk-eval-<hex>；secret 明文仅客户端持有，
 *   服务端存「加密态」（AES-256-GCM，方案 A 验签用）+「哈希态」（sha256，审计/不回显）。
 * - HMAC：canonical(METHOD\nPATH\nsha256(body)) → HMAC-SHA256，常量时间比较（apiKeyAuth 验签用）。
 */

import crypto from "crypto";
import argon2 from "argon2";
import jwt from "jsonwebtoken";
import { getConfig } from "../config";

/* ── 密码 ───────────────────────────────────────────── */
export async function hashPassword(plain: string): Promise<string> {
  return argon2.hash(plain, {
    type: argon2.argon2id,
    memoryCost: 19456, // 19 MiB
    timeCost: 2,
    parallelism: 1,
  });
}

export async function verifyPassword(plain: string, hash: string): Promise<boolean> {
  if (!hash) return false;
  try {
    return await argon2.verify(hash, plain);
  } catch {
    return false;
  }
}

/* ── JWT ────────────────────────────────────────────── */
export const ACCESS_TTL_SEC = 60 * 30; // 30 min
export const REFRESH_TTL_SEC = 60 * 60 * 24 * 14; // 14 days

export interface TokenPayloadInput {
  userId: string;
  orgId?: string | null;
  role?: string | null;
  name?: string | null;
}

export interface TokenClaims extends jwt.JwtPayload {
  kind: "access" | "refresh";
  sub: string;
  org_id: string | null;
  role: string | null;
  name: string | null;
  auth_time: number;
}

function issueToken(payload: TokenPayloadInput, kind: "access" | "refresh"): string {
  const cfg = getConfig();
  const ttl = kind === "access" ? ACCESS_TTL_SEC : REFRESH_TTL_SEC;
  return jwt.sign(
    {
      kind,
      sub: payload.userId,
      org_id: payload.orgId || null,
      role: payload.role || null,
      name: payload.name || null,
      auth_time: Math.floor(Date.now() / 1000),
    },
    cfg.jwtSecret,
    { expiresIn: ttl, algorithm: "HS256" }
  );
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export function issueTokenPair(payload: TokenPayloadInput): TokenPair {
  return {
    access_token: issueToken(payload, "access"),
    refresh_token: issueToken(payload, "refresh"),
    expires_in: ACCESS_TTL_SEC,
  };
}

export function verifyToken(token: string): TokenClaims {
  const cfg = getConfig();
  return jwt.verify(token, cfg.jwtSecret, { algorithms: ["HS256"] }) as TokenClaims;
}

/* ── API Key 对生成 ─────────────────────────────────── */
function randomToken(bytes: number): string {
  return crypto.randomBytes(bytes).toString("hex");
}

export interface ApiKeyPair {
  publicKey: string;
  secretKey: string;
}

/** 生成 (publicKey, secretKey) 对。secret 明文仅本次返回给客户端。 */
export function generateApiKeyPair(): ApiKeyPair {
  return {
    publicKey: `pk-eval-${randomToken(16)}`, // 32 hex
    secretKey: `sk-eval-${randomToken(24)}`, // 48 hex
  };
}

/* ── secret 存储态（方案 A）─────────────────────────── */
function deriveAesKey(): Buffer {
  const cfg = getConfig();
  return crypto.createHash("sha256").update(cfg.keyEncryptionKey).digest();
}

/** 加密 secret 明文 → "v1:<iv_b64>:<ct_b64>:<tag_b64>"（可逆，验签用）。 */
export function encryptSecret(plain: string): string {
  const key = deriveAesKey();
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ct = Buffer.concat([cipher.update(plain, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return ["v1", iv.toString("base64"), ct.toString("base64"), tag.toString("base64")].join(
    ":"
  );
}

/** 解密 → secret 明文。 */
export function decryptSecret(serialized: string): string {
  const parts = String(serialized).split(":");
  if (parts.length !== 4 || parts[0] !== "v1") {
    throw new Error("invalid secret ciphertext");
  }
  const [, ivB64, ctB64, tagB64] = parts;
  const key = deriveAesKey();
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(ivB64, "base64"));
  decipher.setAuthTag(Buffer.from(tagB64, "base64"));
  const pt = Buffer.concat([
    decipher.update(Buffer.from(ctB64, "base64")),
    decipher.final(),
  ]);
  return pt.toString("utf8");
}

/** secret 的 sha256 哈希（hex）——审计/不回显用。 */
export function hashSecret(plain: string): string {
  return crypto.createHash("sha256").update(plain).digest("hex");
}

/* ── HMAC 签名（apiKeyAuth 验签）────────────────────── */
/**
 * canonical = METHOD + "\n" + PATH + "\n" + sha256(body)
 * signature = hex(HMAC_SHA256(secret, canonical))
 * （§6.3，评估器与平台必须一致）
 */
export function canonicalString(method: string, path: string, body?: Buffer | string): string {
  const bodyHash = crypto
    .createHash("sha256")
    .update(body ? Buffer.from(body) : Buffer.alloc(0))
    .digest("hex");
  return `${method.toUpperCase()}\n${path}\n${bodyHash}`;
}

export function signHmac(
  secret: string,
  method: string,
  path: string,
  body?: Buffer | string
): string {
  return crypto
    .createHmac("sha256", secret)
    .update(canonicalString(method, path, body))
    .digest("hex");
}

export function timingSafeEqualHex(a: string, b: string): boolean {
  const ab = Buffer.from(a, "hex");
  const bb = Buffer.from(b, "hex");
  if (ab.length !== bb.length || ab.length === 0) return false;
  return crypto.timingSafeEqual(ab, bb);
}

/** 组装 Authorization 头值：`Eval <publicKey>:<signature>`。 */
export function authHeader(publicKey: string, signature: string): string {
  return `Eval ${publicKey}:${signature}`;
}

export interface ParsedAuthHeader {
  scheme: "Eval";
  publicKey: string;
  signature: string;
}

/** 解析 Authorization 头 → { scheme, publicKey, signature } | null。 */
export function parseAuthHeader(
  header?: string
): ParsedAuthHeader | null {
  if (!header || typeof header !== "string") return null;
  const m = header.match(/^Eval\s+([^:\s]+):([0-9a-f]+)$/i);
  if (!m) return null;
  return { scheme: "Eval", publicKey: m[1], signature: m[2].toLowerCase() };
}
