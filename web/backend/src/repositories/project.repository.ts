/**
 * 项目数据访问（租户隔离：所有查询强制 org_id 过滤）。
 * 隔离为数据层硬约束：findXxx 一律带 orgId，缺则抛 FORBIDDEN。
 */

import { Project } from "@prisma/client"
import { BaseRepository, type Tenant } from "./base.repository"

export interface ProjectCreateInput {
  slug: string
  name: string
  description?: string | null
  defaultRuleSet?: string | null
  defaultTaskSet?: string | null
  retentionDays?: number | null
}

class ProjectRepository extends BaseRepository {
  constructor(tenant?: Tenant) {
    super(tenant)
  }

  /** 列出组织下项目（可选仅未归档）。 */
  listByOrg(opts: { includeArchived?: boolean } = {}): Promise<Project[]> {
    const orgId = this.requireOrg()
    return this.prisma.project.findMany({
      where: {
        orgId,
        ...(opts.includeArchived ? {} : { archivedAt: null }),
      },
      orderBy: { createdAt: "desc" },
    })
  }

  /**
   * 按 id 查项目（强制属于当前 org；不属于则返回 null —— 调用方按 404 处理，
   * 不泄露存在性，§6.4）。
   */
  findByIdSafe(projectId: string): Promise<Project | null> {
    const orgId = this.requireOrg()
    return this.prisma.project.findFirst({
      where: { id: projectId, orgId },
    })
  }

  /**
   * 全局按 id 查（无 org 过滤）——仅供 tenantGuard 自举解析项目归属用；
   * 业务层禁止直接调用，隔离由随后 membership 校验保证。
   */
  findByIdAny(projectId: string): Promise<Project | null> {
    return this.prisma.project.findUnique({ where: { id: projectId } })
  }

  create(data: ProjectCreateInput): Promise<Project> {
    const orgId = this.requireOrg()
    return this.prisma.project.create({
      data: {
        orgId,
        slug: data.slug,
        name: data.name,
        description: data.description ?? null,
        defaultRuleSet: data.defaultRuleSet ?? null,
        defaultTaskSet: data.defaultTaskSet ?? null,
        retentionDays: data.retentionDays ?? null,
        createdBy: this.tenant.userId!,
      },
    })
  }

  update(projectId: string, patch: Partial<Project>): Promise<{ count: number }> {
    const orgId = this.requireOrg()
    return this.prisma.project.updateMany({
      where: { id: projectId, orgId },
      data: patch,
    })
  }

  setArchived(projectId: string, archived: boolean): Promise<{ count: number }> {
    const orgId = this.requireOrg()
    return this.prisma.project.updateMany({
      where: { id: projectId, orgId },
      data: { archivedAt: archived ? new Date() : null },
    })
  }
}

export { ProjectRepository }
