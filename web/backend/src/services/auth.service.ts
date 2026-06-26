/**
 * 认证业务（注册/登录/刷新）。
 *
 * 注册：邮箱+密码 → 建 user。**不再自动建个人 Org**（纯团队中心模型）：
 * 新用户登录后无团队，需「创建团队」或「申请加入团队」（见 org.service / join request）。
 * 邮箱应用层小写归一；PLATFORM_ALLOW_SIGNUP 控制是否开放注册。
 */

import { UserRepository } from "../repositories/user.repository"
import {
  hashPassword,
  verifyPassword,
  issueTokenPair,
  verifyToken,
  type TokenPair,
} from "../infra/crypto"
import { getConfig } from "../config"
import { PlatformError } from "../middleware/errorHandler"

const userRepo = new UserRepository()

function assertEmail(email?: string): asserts email is string {
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    throw new PlatformError("invalid email", { status: 400, code: "SCHEMA_INVALID" })
  }
}
function assertPassword(password?: string): asserts password is string {
  if (!password || password.length < 8) {
    throw new PlatformError("password must be >= 8 chars", {
      status: 400,
      code: "SCHEMA_INVALID",
    })
  }
}

export interface RegisterInput {
  email?: string
  password?: string
  name?: string
}
export interface AuthPublicUser {
  id: string
  email: string
  name: string | null
}
export interface RegisterResult extends TokenPair {
  user: AuthPublicUser
}
export interface LoginResult extends TokenPair {
  user: AuthPublicUser
}

/** 注册：建用户（不再建个人 Org）。 */
export async function register(input: RegisterInput): Promise<RegisterResult> {
  const cfg = getConfig()
  if (!cfg.allowSignup) {
    throw new PlatformError("signup disabled", { status: 403, code: "SIGNUP_DISABLED" })
  }
  assertEmail(input.email)
  assertPassword(input.password)

  const normalizedEmail = input.email.toLowerCase()
  const existing = await userRepo.findByEmail(normalizedEmail)
  if (existing) {
    throw new PlatformError("email already registered", { status: 409, code: "EMAIL_TAKEN" })
  }

  const passwordHash = await hashPassword(input.password)
  const user = await userRepo.create({
    email: normalizedEmail,
    passwordHash,
    name: input.name || null,
  })

  // 无团队：token 不带 orgId（鉴权不依赖它；前端 me() memberships 为空 → 引导创建/加入团队）
  const tokens = issueTokenPair({ userId: user.id, name: user.name })
  return {
    user: { id: user.id, email: user.email, name: user.name },
    ...tokens,
  }
}

/** 登录：校验密码 → 签发（以用户首个组织为默认上下文，无团队则空）。 */
export async function login(input: { email?: string; password?: string }): Promise<LoginResult> {
  assertEmail(input.email)
  const user = await userRepo.findByEmail(input.email)
  if (!user || !user.passwordHash) {
    // 账号不存在 或 SSO-only 用户（无密码）→ 统一返回 invalid
    throw new PlatformError("invalid credentials", { status: 401, code: "AUTH_INVALID" })
  }
  const ok = await verifyPassword(input.password!, user.passwordHash)
  if (!ok) {
    throw new PlatformError("invalid credentials", { status: 401, code: "AUTH_INVALID" })
  }
  const memberships = await userRepo.listMemberships(user.id)
  const primary = memberships[0]
  const tokens = issueTokenPair({
    userId: user.id,
    orgId: primary ? primary.orgId : undefined,
    role: primary ? primary.role : undefined,
    name: user.name,
  })
  return {
    user: { id: user.id, email: user.email, name: user.name },
    ...tokens,
  }
}

/** 刷新：校验 refresh token → 重发（保留同一 org/role 上下文）。 */
export async function refresh(input: { refresh_token?: string }): Promise<TokenPair> {
  let payload
  try {
    payload = verifyToken(input.refresh_token!)
  } catch {
    throw new PlatformError("invalid or expired refresh token", {
      status: 401,
      code: "AUTH_INVALID",
    })
  }
  if (payload.kind !== "refresh") {
    throw new PlatformError("not a refresh token", { status: 401, code: "AUTH_INVALID" })
  }
  return issueTokenPair({
    userId: payload.sub,
    orgId: payload.org_id || undefined,
    role: payload.role || undefined,
  })
}

/** 当前用户信息 + 成员关系。 */
export async function me(userId: string) {
  const user = await userRepo.findById(userId)
  if (!user) throw new PlatformError("user not found", { status: 404, code: "NOT_FOUND" })
  const memberships = await userRepo.listMemberships(userId)
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    memberships: memberships.map((m) => ({
      orgId: m.orgId,
      role: m.role,
      org: { id: m.org.id, name: m.org.name, slug: m.org.slug },
    })),
  }
}

export const AuthService = { register, login, refresh, me }
