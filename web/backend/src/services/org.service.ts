/**
 * 组织业务：成员管理（邀请/移除/列表）+ 创建团队 Org。
 * owner 角色限定（路由 orgGuard 强制）。
 */

import { OrgRepository, UserRepository } from "../repositories/user.repository"
import { AuditService } from "./audit.service"
import { PlatformError } from "../middleware/errorHandler"
import { getPrisma } from "../infra/prisma"
import { slugify, uniquify } from "../utils/slug"
import type { Tenant } from "../repositories/base.repository"

const orgRepo = new OrgRepository()
const userRepo = new UserRepository()

export interface OrgService {
  listMembers: () => Promise<
    { userId: string; role: string; email: string; name: string | null; joinedAt: Date }[]
  >
  inviteMember: (input: {
    email?: string
    role?: string
  }) => Promise<{ userId: string; email: string; role: string }>
  removeMember: (userId: string) => Promise<{ removed: boolean }>
}

export function createOrgService(tenant: Tenant): OrgService {
  async function listMembers() {
    const rows = await orgRepo.listMembers(tenant.orgId!)
    return rows.map((r) => ({
      userId: r.userId,
      role: r.role,
      email: r.user.email,
      name: r.user.name,
      joinedAt: r.createdAt,
    }))
  }

  async function inviteMember(input: { email?: string; role?: string }) {
    if (!input.email) {
      throw new PlatformError("email required", { status: 400, code: "SCHEMA_INVALID" })
    }
    const user = await userRepo.findByEmail(input.email)
    if (!user) throw new PlatformError("user not found", { status: 404, code: "NOT_FOUND" })
    const existing = await orgRepo.findMembership(tenant.orgId!, user.id)
    if (existing) {
      throw new PlatformError("already a member", { status: 409, code: "CONFLICT" })
    }
    const finalRole = input.role === "owner" ? "owner" : "member"
    await orgRepo.addMember({ orgId: tenant.orgId!, userId: user.id, role: finalRole })
    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "member.invite",
      targetType: "user",
      targetId: user.id,
      metadata: { role: finalRole, email: input.email },
    })
    return { userId: user.id, email: user.email, role: finalRole }
  }

  async function removeMember(userId: string) {
    if (userId === tenant.userId) {
      throw new PlatformError("cannot remove self", { status: 400, code: "CONFLICT" })
    }
    const m = await orgRepo.findMembership(tenant.orgId!, userId)
    if (!m) throw new PlatformError("not found", { status: 404, code: "NOT_FOUND" })
    await orgRepo.removeMember(tenant.orgId!, userId)
    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "member.remove",
      targetType: "user",
      targetId: userId,
    })
    return { removed: true }
  }

  return { listMembers, inviteMember, removeMember }
}

/**
 * 创建团队 Org（事务：slug 唯一化 → organization.create → owner membership）。
 * 复刻 auth.service register 原「建 Org」事务结构（已移除个人 Org 自动创建）。
 */
export async function createTeamOrg(input: {
  userId: string
  name?: string
}): Promise<{ id: string; name: string; slug: string }> {
  const name = (input.name || "").trim()
  if (!name) {
    throw new PlatformError("org name required", { status: 400, code: "SCHEMA_INVALID" })
  }
  const prisma = getPrisma()
  const baseSlug = slugify(name) || "team"
  const result = await prisma.$transaction(async (tx) => {
    let slug = baseSlug
    if (await tx.organization.findUnique({ where: { slug } })) {
      slug = uniquify(baseSlug)
    }
    const org = await tx.organization.create({
      data: { name, slug, createdBy: input.userId },
    })
    await tx.orgMembership.create({
      data: { orgId: org.id, userId: input.userId, role: "owner" },
    })
    return { org }
  })
  await AuditService.log({
    actorUserId: input.userId,
    action: "org.create",
    targetType: "organization",
    targetId: result.org.id,
    metadata: { name, slug: result.org.slug },
  })
  return { id: result.org.id, name: result.org.name, slug: result.org.slug }
}
