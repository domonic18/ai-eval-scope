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
    {
      userId: string
      role: string
      email: string
      name: string | null
      joinedAt: Date
      lastActive: Date | null
    }[]
  >
  /** 已注册邮箱 → 直加入；未注册 → 建待接受邀请（注册后自动加入）。 */
  inviteMember: (input: {
    email?: string
    role?: string
  }) => Promise<
    | { kind: "member"; userId: string; email: string; role: string }
    | { kind: "invitation"; email: string; role: string }
  >
  removeMember: (userId: string) => Promise<{ removed: boolean }>
  /** 角色变更 / 所有权转移（demoteSelf：提升他人同时降级自己，事务原子）。 */
  updateMemberRole: (
    targetUserId: string,
    input: { role?: string; demoteSelf?: boolean },
  ) => Promise<{ userId: string; role: string; selfDemoted: boolean }>
  listInvitations: () => Promise<
    {
      id: string
      email: string
      role: string
      createdAt: Date
      resentAt: Date | null
      inviter: { id: string; name: string | null; email: string }
    }[]
  >
  resendInvitation: (id: string) => Promise<{ resent: boolean }>
  revokeInvitation: (id: string) => Promise<{ revoked: boolean }>
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
      lastActive: r.user.lastLoginAt,
    }))
  }

  async function inviteMember(input: { email?: string; role?: string }) {
    if (!input.email) {
      throw new PlatformError("email required", { status: 400, code: "SCHEMA_INVALID" })
    }
    const finalRole = input.role === "owner" ? "owner" : "member"
    const user = await userRepo.findByEmail(input.email)
    if (user) {
      // 已注册：同步加入
      const existing = await orgRepo.findMembership(tenant.orgId!, user.id)
      if (existing) {
        throw new PlatformError("already a member", { status: 409, code: "CONFLICT" })
      }
      await orgRepo.addMember({ orgId: tenant.orgId!, userId: user.id, role: finalRole })
      await AuditService.log({
        orgId: tenant.orgId,
        actorUserId: tenant.userId,
        action: "member.invite",
        targetType: "user",
        targetId: user.id,
        metadata: { role: finalRole, email: input.email },
      })
      return { kind: "member" as const, userId: user.id, email: user.email, role: finalRole }
    }
    // 未注册：建待接受邀请（对方注册后自动加入）
    const pending = await orgRepo.findPendingInvitation(tenant.orgId!, input.email)
    if (pending) {
      throw new PlatformError("invitation already pending", { status: 409, code: "CONFLICT" })
    }
    await orgRepo.createInvitation({
      orgId: tenant.orgId!,
      email: input.email,
      role: finalRole,
      invitedBy: tenant.userId!,
    })
    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "member.invite",
      targetType: "invitation",
      targetId: input.email.toLowerCase(),
      metadata: { role: finalRole, email: input.email, invitation: true },
    })
    return { kind: "invitation" as const, email: input.email.toLowerCase(), role: finalRole }
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

  async function updateMemberRole(
    targetUserId: string,
    input: { role?: string; demoteSelf?: boolean },
  ) {
    const role = input.role
    if (role !== "owner" && role !== "member") {
      throw new PlatformError("role must be owner or member", {
        status: 400,
        code: "SCHEMA_INVALID",
      })
    }
    // demoteSelf：同时把调用方降为 member（与 role=owner 组合即所有权转移），正交参数
    const demoteSelf = input.demoteSelf === true
    if (targetUserId === tenant.userId) {
      throw new PlatformError("cannot change own role", { status: 400, code: "CONFLICT" })
    }
    const orgId = tenant.orgId!
    const prisma = getPrisma()
    const result = await prisma.$transaction(async (tx) => {
      const target = await tx.orgMembership.findUnique({
        where: { orgId_userId: { orgId, userId: targetUserId } },
      })
      if (!target) throw new PlatformError("not found", { status: 404, code: "NOT_FOUND" })
      const self = await tx.orgMembership.findUnique({
        where: { orgId_userId: { orgId, userId: tenant.userId! } },
      })
      if (!self) throw new PlatformError("not found", { status: 404, code: "NOT_FOUND" })
      const selfLosesOwner = demoteSelf && self.role === "owner"
      if (target.role === role && !selfLosesOwner) {
        // 同角色且自身无降级需求 → 幂等 no-op（不审计）
        return { userId: targetUserId, role, selfDemoted: false, changed: false }
      }
      // 防御性：按变更后净值校验至少剩 1 名 owner（转移=自己-1、目标+1，净不变，合法）
      const owners = await tx.orgMembership.count({ where: { orgId, role: "owner" } })
      const targetGainsOwner = target.role === "member" && role === "owner"
      const targetLosesOwner = target.role === "owner" && role === "member"
      const ownersAfter =
        owners - (selfLosesOwner ? 1 : 0) + (targetGainsOwner ? 1 : 0) - (targetLosesOwner ? 1 : 0)
      if (ownersAfter < 1) {
        throw new PlatformError("cannot demote the last owner", { status: 400, code: "CONFLICT" })
      }
      if (target.role !== role) {
        await tx.orgMembership.update({
          where: { orgId_userId: { orgId, userId: targetUserId } },
          data: { role },
        })
      }
      let selfDemoted = false
      if (selfLosesOwner) {
        await tx.orgMembership.update({
          where: { orgId_userId: { orgId, userId: tenant.userId! } },
          data: { role: "member" },
        })
        selfDemoted = true
      }
      return { userId: targetUserId, role, selfDemoted, changed: true }
    })
    if (result.changed) {
      await AuditService.log({
        orgId: tenant.orgId,
        actorUserId: tenant.userId,
        action: "member.update_role",
        targetType: "user",
        targetId: targetUserId,
        metadata: { role, demoteSelf, selfDemoted: result.selfDemoted },
      })
    }
    return { userId: result.userId, role: result.role, selfDemoted: result.selfDemoted }
  }

  async function listInvitations() {
    const rows = await orgRepo.listInvitations(tenant.orgId!)
    return rows.map((r) => ({
      id: r.id,
      email: r.email,
      role: r.role,
      createdAt: r.createdAt,
      resentAt: r.resentAt,
      inviter: { id: r.inviter.id, name: r.inviter.name, email: r.inviter.email },
    }))
  }

  async function resendInvitation(id: string) {
    const inv = await orgRepo.findInvitation(tenant.orgId!, id)
    if (!inv) throw new PlatformError("not found", { status: 404, code: "NOT_FOUND" })
    if (inv.status !== "pending") {
      throw new PlatformError("invitation not pending", { status: 409, code: "CONFLICT" })
    }
    await orgRepo.touchInvitation(id)
    return { resent: true }
  }

  async function revokeInvitation(id: string) {
    const inv = await orgRepo.findInvitation(tenant.orgId!, id)
    if (!inv) throw new PlatformError("not found", { status: 404, code: "NOT_FOUND" })
    if (inv.status !== "pending") {
      throw new PlatformError("invitation not pending", { status: 409, code: "CONFLICT" })
    }
    await orgRepo.setInvitationStatus(id, "revoked")
    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "member.invite_revoke",
      targetType: "invitation",
      targetId: inv.email,
    })
    return { revoked: true }
  }

  return {
    listMembers,
    inviteMember,
    removeMember,
    updateMemberRole,
    listInvitations,
    resendInvitation,
    revokeInvitation,
  }
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
