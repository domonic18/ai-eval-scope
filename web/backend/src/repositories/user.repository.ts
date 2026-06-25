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
  }): Promise<User> {
    // passwordHash 可选：SSO 用户无密码（docs/arch/12 §4.2）
    return this.prisma.user.create({
      data: {
        email: String(p.email).toLowerCase(),
        passwordHash: p.passwordHash ?? null,
        name: p.name ?? null,
      },
    })
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
  create(p: { name: string; slug: string; createdBy: string }): Promise<Organization> {
    return this.prisma.organization.create({
      data: { name: p.name, slug: p.slug, createdBy: p.createdBy },
    })
  }
  listMembers(orgId: string) {
    return this.prisma.orgMembership.findMany({
      where: { orgId },
      include: { user: { select: { id: true, email: true, name: true } } },
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
}

export { UserRepository, OrgRepository }
