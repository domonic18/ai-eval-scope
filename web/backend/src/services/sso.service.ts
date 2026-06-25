/**
 * SAML SSO 业务（docs/arch/12 §4）。
 *
 * 与公司统一 IdP「光华平台」（SAML 2.0，SP-Initiated）对接，与 SquadSight 平级。
 * 光华 IdP 免 SP 注册（不校验 SP 身份/签名请求），仅需复用其公开 IdP 参数 + 公钥证书。
 *
 * 流程：
 *   /login  → 生成 AuthnRequest（记录 request_id）→ 302 跳光华登录
 *   /acs    → 验签 SAML Response → InResponseTo 防重放 → 提取用户 → 匹配/建号 → 签 JWT
 *            → 生成一次性 exchange code → 302 回前端 /login?sso=success&code=xxx
 *   /exchange → 校验消费 code（60s TTL）→ 返回 token pair
 *
 * 用户匹配（§4.4，复用 SquadSight 语义）：
 *   a. email 命中已有 User → 绑定 sso_name_id（password→saml 单向，保留 passwordHash）
 *   b. sso_name_id 命中   → 更新最近登录
 *   c. 都未命中           → 新建 User(auth_type=saml) + 个人 Organization(owner)
 *
 * 决策 D5：SSO 建号不受 PLATFORM_ALLOW_SIGNUP 约束（SSO 用户已由公司 IdP 认证）。
 */

import crypto from "crypto"
import saml2 from "saml2-js"
import { Prisma, User } from "@prisma/client"
import { getPrisma } from "../infra/prisma"
import { UserRepository } from "../repositories/user.repository"
import { issueTokenPair } from "../infra/crypto"
import { getSamlConfig, validateSamlConfig } from "../config"
import { slugify, uniquify } from "../utils/slug"
import { PlatformError } from "../middleware/errorHandler"

const userRepo = new UserRepository()
const SSO_PROVIDER = "guanghua"

/* ── SP / IdP 单例（按配置构建一次）────────────────────── */
let _sp: saml2.ServiceProvider | null = null
let _idp: saml2.IdentityProvider | null = null

/** 纯 base64（无 PEM 标签/换行）→ 标准 PEM。env 可存裸 base64，便于配置。 */
function formatPem(raw: string, type: "CERTIFICATE" | "PRIVATE KEY"): string {
  if (!raw) return ""
  const clean = raw
    .replace(/-----BEGIN [A-Z ]+-----/g, "")
    .replace(/-----END [A-Z ]+-----/g, "")
    .replace(/\s+/g, "")
  if (!clean) return ""
  const lines = clean.match(/.{1,64}/g) || [clean]
  return `-----BEGIN ${type}-----\n${lines.join("\n")}\n-----END ${type}-----`
}

function getSp(): saml2.ServiceProvider {
  if (_sp) return _sp
  const cfg = getSamlConfig()
  _sp = new saml2.ServiceProvider({
    entity_id: cfg.spEntityId,
    private_key: formatPem(cfg.spKey, "PRIVATE KEY"),
    certificate: formatPem(cfg.spCert, "CERTIFICATE"),
    assert_endpoint: cfg.acsUrl,
    allow_unencrypted_assertion: true, // 对齐 SquadSight 宽松策略
  })
  return _sp
}

function getIdp(): saml2.IdentityProvider {
  if (_idp) return _idp
  const cfg = getSamlConfig()
  _idp = new saml2.IdentityProvider({
    sso_login_url: cfg.idpSsoUrl,
    sso_logout_url: cfg.idpSlsUrl,
    certificates: formatPem(cfg.idpCert, "CERTIFICATE"),
    allow_unencrypted_assertion: true,
  })
  return _idp
}

/** 仅供测试重置单例（测试改 env 后重建 SP/IdP）。 */
export function __resetSsoCacheForTest(): void {
  _sp = null
  _idp = null
}

/* ── AuthnRequest request_id 防重放缓存（InResponseTo 校验）── */
const REQUEST_TTL_MS = 60_000
const pendingRequests = new Map<string, number>()

function rememberRequest(requestId: string): void {
  pendingRequests.set(requestId, Date.now() + REQUEST_TTL_MS)
  if (pendingRequests.size > 1000) cleanupRequests()
}
function consumeRequest(inResponseTo: string): boolean {
  const exp = pendingRequests.get(inResponseTo)
  if (exp === undefined) return false
  pendingRequests.delete(inResponseTo)
  return Date.now() <= exp
}
function cleanupRequests(): void {
  const now = Date.now()
  for (const [k, exp] of pendingRequests) {
    if (exp <= now) pendingRequests.delete(k)
  }
}

/* ── 一次性 exchange code 缓存（JWT 不入 URL/Referer）── */
const CODE_TTL_MS = 60_000

interface SsoSession {
  access_token: string
  refresh_token: string
  expires_in: number
  user: { id: string; email: string; name: string | null }
  org?: { id: string; name: string; slug: string }
  exp: number
}
const codes = new Map<string, SsoSession>()

function issueCode(s: Omit<SsoSession, "exp">): string {
  const code = crypto.randomBytes(24).toString("hex")
  codes.set(code, { ...s, exp: Date.now() + CODE_TTL_MS })
  return code
}
function consumeCode(code: string): SsoSession | null {
  const v = codes.get(code)
  if (!v) return null
  codes.delete(code)
  return Date.now() <= v.exp ? v : null
}

/* ── saml2-js 回调 → Promise 包装 ─────────────────────── */
function createLoginRequestUrl(): Promise<{ login_url: string; request_id: string }> {
  return new Promise((resolve, reject) => {
    getSp().create_login_request_url(getIdp(), {}, (err, login_url, request_id) => {
      if (err) return reject(err)
      resolve({ login_url: login_url ?? "", request_id: request_id ?? "" })
    })
  })
}

function postAssert(samlResponse: string): Promise<saml2.SAMLAssertResponse> {
  return new Promise((resolve, reject) => {
    getSp().post_assert(
      getIdp(),
      {
        request_body: { SAMLResponse: samlResponse },
        allow_unencrypted_assertion: true,
        require_session_index: false,
      },
      (err, response) => {
        if (err) return reject(err)
        resolve(response)
      },
    )
  })
}

/* ── 配置校验 ────────────────────────────────────────── */
function ensureEnabled(): void {
  const cfg = getSamlConfig()
  if (!cfg.enabled) {
    throw new PlatformError("SSO disabled", { status: 503, code: "SSO_DISABLED" })
  }
  const missing = validateSamlConfig(cfg)
  if (missing.length) {
    throw new PlatformError(`SSO misconfigured: missing ${missing.join(", ")}`, {
      status: 500,
      code: "SSO_CONFIG",
    })
  }
}

/* ── 对外能力 ────────────────────────────────────────── */
export function isSsoEnabled(): boolean {
  return getSamlConfig().enabled
}

export function getMetadata(): string {
  ensureEnabled()
  return getSp().create_metadata()
}

/** 发起 SSO 登录：生成 AuthnRequest URL（前端跳转到此 URL → 光华登录）。 */
export async function startLogin(): Promise<{ redirect_url: string }> {
  ensureEnabled()
  const { login_url, request_id } = await createLoginRequestUrl()
  if (!request_id) {
    throw new PlatformError("SAML AuthnRequest 未生成 request_id", {
      status: 500,
      code: "SSO_CONFIG",
    })
  }
  rememberRequest(request_id)
  return { redirect_url: login_url }
}

/** 处理光华 ACS 回调：验签 + 防重放 + 匹配/建号 + 签 JWT + 签发一次性 code。 */
export async function handleAcs(samlResponse: string): Promise<{ code: string }> {
  ensureEnabled()

  let assertion: saml2.SAMLAssertResponse
  try {
    assertion = await postAssert(samlResponse)
  } catch {
    throw new PlatformError("SAML Response 验证失败", { status: 401, code: "SSO_INVALID" })
  }

  // InResponseTo 防重放（对齐 SquadSight）
  const inResponseTo = assertion.response_header?.in_response_to
  if (inResponseTo && !consumeRequest(inResponseTo)) {
    throw new PlatformError("SAML Response 重放/请求 ID 不匹配", {
      status: 401,
      code: "SSO_REPLAY",
    })
  }

  const u = assertion.user
  const nameId = u?.name_id || ""
  if (!nameId) {
    throw new PlatformError("SAML NameID 缺失", { status: 401, code: "SSO_INVALID" })
  }
  const email = extractEmail(u, nameId)
  const name = u?.name || u?.given_name || email.split("@")[0]
  const attributes = normalizeAttributes(u?.attributes)

  const { user, org } = await matchOrCreateSsoUser({ email, name, nameId, attributes })
  const tokens = issueTokenPair({
    userId: user.id,
    orgId: org?.id,
    role: org ? "owner" : undefined,
    name: user.name,
  })
  const code = issueCode({
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token,
    expires_in: tokens.expires_in,
    user: { id: user.id, email: user.email, name: user.name },
    org,
  })
  return { code }
}

/** 用一次性 code 换 token pair（前端在 /login?sso=success&code=xxx 调用）。 */
export function exchangeCode(code: string): SsoSession {
  const s = consumeCode(code)
  if (!s) {
    throw new PlatformError("invalid or expired sso code", {
      status: 401,
      code: "SSO_CODE_INVALID",
    })
  }
  return s
}

/* ── 属性提取（对齐 SquadSight 优先级）────────────────── */
type SamlUser = saml2.SAMLAssertResponse["user"]

function firstAttr(v: string | string[] | undefined): string | undefined {
  if (v === undefined) return undefined
  return Array.isArray(v) ? v[0] : v
}

function extractEmail(u: SamlUser | undefined, nameId: string): string {
  const candidates = [
    u?.email,
    u?.upn,
    firstAttr(u?.attributes?.email),
    firstAttr(u?.attributes?.mail),
    firstAttr(u?.attributes?.userPrincipalName),
  ]
  for (const c of candidates) {
    if (c && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c)) return c.toLowerCase()
  }
  if (nameId.includes("@")) return nameId.toLowerCase()
  return `${nameId}@sso.local`
}

function normalizeAttributes(attrs: SamlUser["attributes"] | undefined): Record<string, unknown> {
  if (!attrs) return {}
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(attrs)) {
    out[k] = Array.isArray(v) ? (v.length === 1 ? v[0] : v) : v
  }
  return out
}

/* ── 用户匹配/建号（§4.4）────────────────────────────── */
async function matchOrCreateSsoUser(p: {
  email: string
  name: string
  nameId: string
  attributes: Record<string, unknown>
}): Promise<{ user: User; org?: { id: string; name: string; slug: string } }> {
  const prisma = getPrisma()
  const attrsJson = p.attributes as Prisma.InputJsonValue

  // a. email 命中 → 绑定 SAML（password→saml 单向，保留 passwordHash）
  const byEmail = await userRepo.findByEmail(p.email)
  if (byEmail) {
    const user = await prisma.user.update({
      where: { id: byEmail.id },
      data: {
        authType: "saml",
        ssoProvider: byEmail.ssoProvider || SSO_PROVIDER,
        ssoNameId: byEmail.ssoNameId || p.nameId,
        ssoAttributes: attrsJson,
        lastSsoLoginAt: new Date(),
      },
    })
    return { user }
  }

  // b. nameId 命中 → 更新最近登录
  const byNameId = await userRepo.findBySsoNameId(p.nameId)
  if (byNameId) {
    const user = await prisma.user.update({
      where: { id: byNameId.id },
      data: { lastSsoLoginAt: new Date(), ssoAttributes: attrsJson },
    })
    return { user }
  }

  // c. 新建 User(auth_type=saml) + 个人 Organization(owner)，事务
  const baseSlug = slugify(p.name || p.email.split("@")[0]) || "org"
  const result = await prisma.$transaction(async (tx) => {
    const user = await tx.user.create({
      data: {
        email: p.email.toLowerCase(),
        passwordHash: null,
        name: p.name,
        authType: "saml",
        ssoProvider: SSO_PROVIDER,
        ssoNameId: p.nameId,
        ssoAttributes: attrsJson,
        lastSsoLoginAt: new Date(),
      },
    })
    let slug = baseSlug
    if (await tx.organization.findUnique({ where: { slug } })) {
      slug = uniquify(baseSlug)
    }
    const org = await tx.organization.create({
      data: { name: `${p.name}'s Org`, slug, createdBy: user.id },
    })
    await tx.orgMembership.create({
      data: { orgId: org.id, userId: user.id, role: "owner" },
    })
    return { user, org }
  })
  return {
    user: result.user,
    org: { id: result.org.id, name: result.org.name, slug: result.org.slug },
  }
}

export const SsoService = {
  isSsoEnabled,
  getMetadata,
  startLogin,
  handleAcs,
  exchangeCode,
}
