/** 认证状态：token 持久化（localStorage）+ 当前用户/组织上下文。 */

import type { AuthSession, Membership, User } from "../types"

const KEY = "agent_eval_session"
export const ORG_KEY = "agent_eval_org"

interface Stored {
  access_token: string
  user: User
}

export function loadSession(): Stored | null {
  const raw = localStorage.getItem(KEY)
  return raw ? (JSON.parse(raw) as Stored) : null
}

/** 是否可编辑配置中心资产（平台管理员）。普通用户只读场景包（docs/arch/13）。 */
export function canEditConfig(): boolean {
  return !!loadSession()?.user?.platformAdmin
}

export function saveSession(s: AuthSession & { user: User }): void {
  localStorage.setItem(KEY, JSON.stringify(s))
}

/** 用 /me 的最新结果刷新 session 内的 user（role/platformAdmin/status 变更后即时反映）。 */
export function updateSessionUser(user: User): void {
  const s = loadSession()
  if (s) localStorage.setItem(KEY, JSON.stringify({ ...s, user }))
}

export function clearSession(): void {
  localStorage.removeItem(KEY)
  localStorage.removeItem(ORG_KEY)
}

export function getToken(): string | null {
  return loadSession()?.access_token ?? null
}

/** 当前组织上下文（首登取首个 membership；用户可切换）。 */
export function getActiveOrg(memberships: Membership[]): string | null {
  const stored = localStorage.getItem(ORG_KEY)
  if (stored && memberships.some((m) => m.orgId === stored)) return stored
  return memberships[0]?.orgId ?? null
}

export function setActiveOrg(orgId: string): void {
  localStorage.setItem(ORG_KEY, orgId)
}
