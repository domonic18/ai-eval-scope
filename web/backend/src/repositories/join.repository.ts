/**
 * 团队加入申请数据访问（join_requests）。方案：纯团队中心 + 申请审批。
 */
import { PrismaClient, JoinRequest } from "@prisma/client"
import { getPrisma } from "../infra/prisma"

export type JoinRequestWithOrg = JoinRequest & { org: { name: string; slug: string } }
export type JoinRequestWithUser = JoinRequest & {
  user: { id: string; email: string; name: string | null }
}

export class JoinRequestRepository {
  private prisma: PrismaClient
  constructor() {
    this.prisma = getPrisma()
  }
  create(p: { orgId: string; userId: string; message?: string | null }): Promise<JoinRequest> {
    return this.prisma.joinRequest.create({
      data: { orgId: p.orgId, userId: p.userId, message: p.message ?? null },
    })
  }
  /** 同一 (orgId,userId) 唯一：返回既有申请（任意状态）。 */
  findActive(orgId: string, userId: string): Promise<JoinRequest | null> {
    return this.prisma.joinRequest.findUnique({
      where: { orgId_userId: { orgId, userId } },
    })
  }
  findByUser(userId: string): Promise<JoinRequestWithOrg[]> {
    return this.prisma.joinRequest.findMany({
      where: { userId },
      include: { org: { select: { name: true, slug: true } } },
      orderBy: { createdAt: "desc" },
    })
  }
  findByOrg(orgId: string): Promise<JoinRequestWithUser[]> {
    return this.prisma.joinRequest.findMany({
      where: { orgId },
      include: { user: { select: { id: true, email: true, name: true } } },
      orderBy: { createdAt: "desc" },
    })
  }
  findById(id: string): Promise<JoinRequest | null> {
    return this.prisma.joinRequest.findUnique({ where: { id } })
  }
  updateStatus(id: string, status: string, resolvedBy: string): Promise<JoinRequest> {
    return this.prisma.joinRequest.update({
      where: { id },
      data: { status, resolvedBy, resolvedAt: new Date() },
    })
  }
}
