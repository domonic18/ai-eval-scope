/** 认证状态：token 持久化（localStorage）+ 当前用户/组织上下文。 */

import type { AuthSession, Membership, User } from "../types"

const KEY = "agent_eval_session"
const ORG_KEY = "agent_eval_org"

interface Stored {
  access_token: string
  refresh_token: string
  user: User
}

export function loadSession(): Stored | null {
  const raw = localStorage.getItem(KEY)
  return raw ? (JSON.parse(raw) as Stored) : null
}

export function saveSession(s: AuthSession & { user: User }): void {
  localStorage.setItem(KEY, JSON.stringify(s))
}

export function clearSession(): void {
  localStorage.removeItem(KEY)
  localStorage.removeItem(ORG_KEY)
}

export function getToken(): string | null {
  return loadSession()?.access_token ?? null
}

export function getRefreshToken(): string | null {
  return loadSession()?.refresh_token ?? null
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
