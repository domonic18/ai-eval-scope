/**
 * 审计日志数据访问（§6.5）。组织级，写入须带 orgId。
 */

import { PrismaClient, AuditLog, Prisma } from "@prisma/client"
import { getPrisma } from "../infra/prisma"

export interface AuditEntry {
  orgId?: string | null
  actorUserId?: string | null
  action: string
  targetType?: string | null
  targetId?: string | null
  metadata?: Prisma.InputJsonValue
}

class AuditRepository {
  private prisma: PrismaClient
  constructor() {
    this.prisma = getPrisma()
  }
  log(entry: AuditEntry): Promise<AuditLog> {
    return this.prisma.auditLog.create({
      data: {
        orgId: entry.orgId || null,
        actorUserId: entry.actorUserId || null,
        action: entry.action,
        targetType: entry.targetType || null,
        targetId: entry.targetId || null,
        metadata: entry.metadata ?? undefined,
      },
    })
  }
  listByOrg(orgId: string, opts: { limit?: number } = {}): Promise<AuditLog[]> {
    return this.prisma.auditLog.findMany({
      where: { orgId },
      orderBy: { createdAt: "desc" },
      take: opts.limit ?? 100,
    })
  }
}

export { AuditRepository }
