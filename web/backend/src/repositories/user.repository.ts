/**
 * 用户/组织/成员 数据访问（账号实体，全局表，非租户过滤范畴；
 * 但组织/成员访问须校验当前用户属于该组织——在 service 层与 tenantGuard 完成）。
 */

import { PrismaClient, User, Organization, OrgMembership } from "@prisma/client"
import { getPrisma } from "../infra/prisma"

export type MembershipWithOrg = OrgMembership & { org: Organization }

class UserRepository {
  private prisma: PrismaClient
  constructor() {
    this.prisma = getPrisma()
  }
  findByEmail(email: string): Promise<User | null> {
    return this.prisma.user.findUnique({
      where: { email: String(email).toLowerCase() },
    })
  }
  findById(id: string): Promise<User | null> {
    return this.prisma.user.findUnique({ where: { id } })
  }
  create(p: {
    email: string
    passwordHash?: string | null
    name?: string | null
    role?: string
    status?: string
    lastLoginAt?: Date
  }): Promise<User> {
    // passwordHash 可选：SSO 用户无密码（docs/arch/12 §4.2）
    // role/status 可选：默认由 schema 决定（user/active）；首注册用户由 service 传 "admin"
    return this.prisma.user.create({
      data: {
        email: String(p.email).toLowerCase(),
        passwordHash: p.passwordHash ?? null,
        name: p.name ?? null,
        role: p.role ?? undefined,
        status: p.status ?? undefined,
        lastLoginAt: p.lastLoginAt ?? undefined,
      },
    })
  }
  /** 全平台用户计数（首注册用户判定 + 管理后台统计）。 */
  count(): Promise<number> {
    return this.prisma.user.count()
  }
  /** 刷新最近登录时间（成员页「最近活跃」）。 */
  async touchLogin(userId: string): Promise<void> {
    await this.prisma.user.update({ where: { id: userId }, data: { lastLoginAt: new Date() } })
  }
  /** SSO：按 SAML NameID 查找（docs/arch/12 §4.4 匹配顺序 b）。 */
  findBySsoNameId(nameId: string): Promise<User | null> {
    return this.prisma.user.findUnique({ where: { ssoNameId: nameId } })
  }
  listMemberships(userId: string): Promise<MembershipWithOrg[]> {
    return this.prisma.orgMembership.findMany({
      where: { userId },
      include: { org: true },
    })
  }
}

class OrgRepository {
  private prisma: PrismaClient
  constructor() {
    this.prisma = getPrisma()
  }
  findById(id: string): Promise<Organization | null> {
    return this.prisma.organization.findUnique({ where: { id } })
  }
  findBySlug(slug: string): Promise<Organization | null> {
    return this.prisma.organization.findUnique({ where: { slug } })
  }
  create(p: {
    name: string
    slug: string
    createdBy: string
    isPersonal?: boolean
  }): Promise<Organization> {
    return this.prisma.organization.create({
      data: {
        name: p.name,
        slug: p.slug,
        createdBy: p.createdBy,
        isPersonal: p.isPersonal ?? false,
      },
    })
  }
  listMembers(orgId: string) {
    return this.prisma.orgMembership.findMany({
      where: { orgId },
      include: {
        user: { select: { id: true, email: true, name: true, lastLoginAt: true } },
      },
      orderBy: { createdAt: "asc" },
    })
  }
  findMembership(orgId: string, userId: string): Promise<OrgMembership | null> {
    return this.prisma.orgMembership.findUnique({
      where: { orgId_userId: { orgId, userId } },
    })
  }
  addMember(p: { orgId: string; userId: string; role: string }): Promise<OrgMembership> {
    return this.prisma.orgMembership.create({
      data: { orgId: p.orgId, userId: p.userId, role: p.role },
    })
  }
  removeMember(orgId: string, userId: string): Promise<OrgMembership> {
    return this.prisma.orgMembership.delete({
      where: { orgId_userId: { orgId, userId } },
    })
  }

  // ── 组织邀请（未注册邮箱：注册后自动加入）──
  listInvitations(orgId: string) {
    return this.prisma.orgInvitation.findMany({
      where: { orgId, status: "pending" },
      include: { inviter: { select: { id: true, name: true, email: true } } },
      orderBy: { createdAt: "desc" },
    })
  }
  findInvitation(orgId: string, id: string) {
    return this.prisma.orgInvitation.findFirst({ where: { id, orgId } })
  }
  findPendingInvitation(orgId: string, email: string) {
    return this.prisma.orgInvitation.findFirst({
      where: { orgId, email: String(email).toLowerCase(), status: "pending" },
    })
  }
  createInvitation(p: { orgId: string; email: string; role: string; invitedBy: string }) {
    return this.prisma.orgInvitation.create({
      data: {
        orgId: p.orgId,
        email: String(p.email).toLowerCase(),
        role: p.role,
        invitedBy: p.invitedBy,
      },
    })
  }
  setInvitationStatus(id: string, status: string) {
    return this.prisma.orgInvitation.update({ where: { id }, data: { status } })
  }
  touchInvitation(id: string) {
    return this.prisma.orgInvitation.update({ where: { id }, data: { resentAt: new Date() } })
  }
  /** 注册时按邮箱自动接受全部待接受邀请（建 membership + 标记 accepted）。 */
  async acceptInvitationsForEmail(email: string, userId: string): Promise<number> {
    const normalized = String(email).toLowerCase()
    const pending = await this.prisma.orgInvitation.findMany({
      where: { email: normalized, status: "pending" },
    })
    if (pending.length === 0) return 0
    await this.prisma.$transaction([
      this.prisma.orgMembership.createMany({
        data: pending.map((i) => ({
          orgId: i.orgId,
          userId,
          role: i.role === "owner" ? "owner" : "member",
        })),
        skipDuplicates: true,
      }),
      this.prisma.orgInvitation.updateMany({
        where: { id: { in: pending.map(i => i.id) } },
        data: { status: "accepted" },
      }),
    ])
    return pending.length
  }
}

export { UserRepository, OrgRepository }
