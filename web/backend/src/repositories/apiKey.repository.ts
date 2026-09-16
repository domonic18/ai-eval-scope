/**
 * API Key 数据访问（单一 Bearer token）。
 *
 * 双访问模式：
 *  - findByTokenHash()：鉴权解析用，**全局**查找（无 tenant，先确定 Key 属于哪个 project）。
 *  - listByProject/create/revoke：管理用，**项目级租户过滤**（强制 projectId 属于当前 org）。
 */

import { ApiKey } from "@prisma/client"
import { BaseRepository, type Tenant } from "./base.repository"

export type ApiKeyWithProject = ApiKey & {
  project: { id: string; orgId: string }
}

export interface ApiKeyCreateInput {
  projectId: string
  tokenHash: string
  tokenEncrypted: string
  tokenPreview: string
  name: string
  expiresAt?: Date | null
}

class ApiKeyRepository extends BaseRepository {
  constructor(tenant?: Tenant) {
    super(tenant)
  }

  /** 全局按 tokenHash 查（鉴权解析）。含 project 用于回填 tenant。 */
  findByTokenHash(tokenHash: string): Promise<ApiKeyWithProject | null> {
    return this.prisma.apiKey.findUnique({
      where: { tokenHash },
      include: { project: { select: { id: true, orgId: true } } },
    })
  }

  findById(id: string): Promise<ApiKey | null> {
    return this.prisma.apiKey.findUnique({ where: { id } })
  }

  /** 全局按 Key id 查身份（CLI auth login/status 的 whoami；含项目与组织名）。 */
  findIdentityById(id: string) {
    return this.prisma.apiKey.findUnique({
      where: { id },
      select: {
        id: true,
        name: true,
        scopes: true,
        expiresAt: true,
        revokedAt: true,
        project: {
          select: {
            id: true,
            name: true,
            slug: true,
            org: { select: { id: true, name: true, slug: true } },
          },
        },
      },
    })
  }

  /** 列出项目下 Key（强制 projectId 归属校验）。 */
  listByProject(projectId: string): Promise<ApiKey[]> {
    const orgId = this.requireOrg()
    return this.prisma.apiKey.findMany({
      where: { projectId, project: { orgId } },
      orderBy: { createdAt: "desc" },
    })
  }

  create(data: ApiKeyCreateInput): Promise<ApiKey> {
    return this.prisma.apiKey.create({
      data: {
        projectId: data.projectId,
        tokenHash: data.tokenHash,
        tokenEncrypted: data.tokenEncrypted,
        tokenPreview: data.tokenPreview,
        name: data.name,
        scopes: ["ingest"],
        expiresAt: data.expiresAt ?? null,
        createdBy: this.tenant.userId!,
      },
    })
  }

  revoke(id: string): Promise<ApiKey> {
    return this.prisma.apiKey.update({
      where: { id },
      data: { revokedAt: new Date() },
    })
  }

  /** 异步更新使用统计（鉴权通过后，非阻塞语义）。 */
  recordUsage(id: string, opts: { ip?: string }): Promise<ApiKey> {
    return this.prisma.apiKey.update({
      where: { id },
      data: {
        lastUsedAt: new Date(),
        lastIp: opts.ip || null,
        callCount: { increment: 1 },
      },
    })
  }
}

export { ApiKeyRepository }
