/**
 * 超管后台 — 跨租户列表/详情/变更（不复用 BaseRepository，无 requireOrg 门）。
 * 先例：ProjectRepository.findByIdAny。聚合统计见 adminStats.repository.ts。
 */
import { Prisma } from "@prisma/client"
import { getPrisma } from "../infra/prisma"

const pageOf = (p?: number, s?: number) => {
  const page = Math.max(1, p ?? 1)
  const size = Math.min(200, Math.max(1, s ?? 50))
  return { page, size, skip: (page - 1) * size, take: size }
}

class AdminRepository {
  private prisma = getPrisma()

  /* ── 用户 ─────────────────────────────────────────── */
  listUsers(opts: { search?: string; status?: string; page?: number; size?: number }) {
    const { page, size, skip, take } = pageOf(opts.page, opts.size)
    const where: Prisma.UserWhereInput = {}
    if (opts.status) where.status = opts.status
    if (opts.search) {
      where.OR = [
        { email: { contains: opts.search, mode: "insensitive" } },
        { name: { contains: opts.search, mode: "insensitive" } },
      ]
    }
    return Promise.all([
      this.prisma.user.findMany({
        where,
        orderBy: { createdAt: "desc" },
        skip,
        take,
        select: {
          id: true,
          email: true,
          name: true,
          role: true,
          status: true,
          createdAt: true,
          authType: true,
          lastSsoLoginAt: true,
          _count: { select: { memberships: true } },
        },
      }),
      this.prisma.user.count({ where }),
    ]).then(([items, total]) => ({ items, total, page, size }))
  }

  getUser(id: string) {
    return this.prisma.user.findUnique({
      where: { id },
      select: {
        id: true,
        email: true,
        name: true,
        role: true,
        status: true,
        createdAt: true,
        authType: true,
        memberships: { include: { org: { select: { id: true, name: true, slug: true } } } },
      },
    })
  }

  updateUser(id: string, data: { role?: string; status?: string; name?: string | null }) {
    return this.prisma.user.update({ where: { id }, data })
  }

  createUser(data: {
    email: string
    passwordHash: string
    name?: string | null
    role?: string
  }) {
    return this.prisma.user.create({
      data: {
        email: data.email.toLowerCase(),
        passwordHash: data.passwordHash,
        name: data.name ?? null,
        role: data.role ?? "user",
      },
    })
  }

  /* ── 组织（带成员/项目/run 计数，单条 SQL）────────── */
  async listOrgs(opts: { search?: string; page?: number; size?: number }) {
    const { page, size } = pageOf(opts.page, opts.size)
    const search = opts.search?.trim()
    const rows = await this.prisma.$queryRaw<
      Array<{
        id: string
        name: string
        slug: string
        created_by: string
        created_at: Date
        member_count: bigint
        project_count: bigint
        run_count: bigint
      }>
    >(Prisma.sql`
      SELECT o.id, o.name, o.slug, o.created_by, o.created_at,
             (SELECT COUNT(*) FROM org_memberships m WHERE m.org_id = o.id)::bigint AS member_count,
             (SELECT COUNT(*) FROM projects p WHERE p.org_id = o.id)::bigint AS project_count,
             (SELECT COUNT(*) FROM runs r JOIN projects p ON p.id = r.project_id WHERE p.org_id = o.id)::bigint AS run_count
      FROM organizations o
      ${search ? Prisma.sql`WHERE o.name ILIKE ${"%" + search + "%"} OR o.slug ILIKE ${"%" + search + "%"}` : Prisma.empty}
      ORDER BY o.created_at DESC
      LIMIT ${size} OFFSET ${(page - 1) * size}
    `)
    const total = await this.prisma.organization.count(
      search
        ? { where: { OR: [{ name: { contains: search, mode: "insensitive" } }, { slug: { contains: search, mode: "insensitive" } }] } }
        : undefined,
    )
    return {
      items: rows.map((r) => ({
        id: r.id,
        name: r.name,
        slug: r.slug,
        createdBy: r.created_by,
        createdAt: r.created_at,
        memberCount: Number(r.member_count),
        projectCount: Number(r.project_count),
        runCount: Number(r.run_count),
      })),
      total,
      page,
      size,
    }
  }

  /** 删组织：Organization→Project→Run/ApiKey/Artifact 全级联（onDelete: Cascade）。 */
  deleteOrg(id: string) {
    return this.prisma.organization.delete({ where: { id } })
  }

  /* ── 项目（跨组织）────────────────────────────────── */
  listProjects(opts: { search?: string; archived?: boolean; page?: number; size?: number }) {
    const { page, size, skip, take } = pageOf(opts.page, opts.size)
    const where: Prisma.ProjectWhereInput = {}
    if (opts.archived !== undefined) where.archivedAt = opts.archived ? { not: null } : null
    if (opts.search) {
      where.OR = [
        { name: { contains: opts.search, mode: "insensitive" } },
        { slug: { contains: opts.search, mode: "insensitive" } },
      ]
    }
    return Promise.all([
      this.prisma.project.findMany({
        where,
        orderBy: { createdAt: "desc" },
        skip,
        take,
        include: {
          org: { select: { id: true, name: true } },
          _count: { select: { runs: true, apiKeys: true } },
        },
      }),
      this.prisma.project.count({ where }),
    ]).then(([items, total]) => ({ items, total, page, size }))
  }

  /* ── 运行（全平台）────────────────────────────────── */
  listRuns(opts: {
    status?: string
    from?: Date
    to?: Date
    search?: string
    page?: number
    size?: number
  }) {
    const { page, size, skip, take } = pageOf(opts.page, opts.size)
    const where: Prisma.RunWhereInput = {}
    if (opts.status) where.status = opts.status
    const createdAt: Prisma.DateTimeFilter<"Run"> = {}
    if (opts.from) createdAt.gte = opts.from
    if (opts.to) createdAt.lte = opts.to
    if (opts.from || opts.to) where.createdAt = createdAt
    if (opts.search) {
      where.project = { name: { contains: opts.search, mode: "insensitive" } }
    }
    return Promise.all([
      this.prisma.run.findMany({
        where,
        orderBy: { createdAt: "desc" },
        skip,
        take,
        include: {
          project: { select: { id: true, name: true, org: { select: { id: true, name: true } } } },
        },
      }),
      this.prisma.run.count({ where }),
    ]).then(([items, total]) => ({ items, total, page, size }))
  }

  /* ── 制品 ─────────────────────────────────────────── */
  listArtifacts(opts: { kind?: string; page?: number; size?: number }) {
    const { page, size, skip, take } = pageOf(opts.page, opts.size)
    const where: Prisma.ArtifactWhereInput = {}
    if (opts.kind) where.kind = opts.kind
    return Promise.all([
      this.prisma.artifact.findMany({
        where,
        orderBy: { createdAt: "desc" },
        skip,
        take,
        include: {
          project: { select: { id: true, name: true } },
          run: { select: { id: true, externalRunId: true } },
        },
      }),
      this.prisma.artifact.count({ where }),
    ]).then(([items, total]) => ({
      items: items.map((a) => ({ ...a, sizeBytes: Number(a.sizeBytes) })),
      total,
      page,
      size,
    }))
  }

  /* ── 审计（全平台，含 orgId IS NULL）──────────────── */
  listAudit(opts: { action?: string; page?: number; size?: number }) {
    const { page, size, skip, take } = pageOf(opts.page, opts.size)
    const where: Prisma.AuditLogWhereInput = {}
    if (opts.action) where.action = { contains: opts.action, mode: "insensitive" }
    return Promise.all([
      this.prisma.auditLog.findMany({
        where,
        orderBy: { id: "desc" },
        skip,
        take,
      }),
      this.prisma.auditLog.count({ where }),
    ]).then(([items, total]) => ({ items, total, page, size }))
  }

  /* ── 删除操作（跨租户管理）────────────────────────── */

  /** 删用户：OrgMembership/JoinRequest 均 onDelete:Cascade，自动清理。 */
  deleteUser(id: string) {
    return this.prisma.user.delete({ where: { id } })
  }

  /** 删单条制品（叶子表，无级联）；返回 objectKey 供 best-effort 清对象存储，不存在返回 null。 */
  async deleteArtifact(id: string): Promise<string | null> {
    const a = await this.prisma.artifact.findUnique({ where: { id }, select: { objectKey: true } })
    if (!a) return null
    await this.prisma.artifact.delete({ where: { id } })
    return a.objectKey
  }

  /** 批量删制品：单事务原子，返回待清理的 objectKey 列表。 */
  async deleteArtifacts(ids: string[]): Promise<string[]> {
    if (!ids.length) return []
    return this.prisma.$transaction(async (tx) => {
      const arts = await tx.artifact.findMany({ where: { id: { in: ids } }, select: { objectKey: true } })
      await tx.artifact.deleteMany({ where: { id: { in: ids } } })
      return arts.map((a) => a.objectKey)
    })
  }

  /** 删项目：事务内先取关联 artifact objectKey，再 project.delete（DB 级联删 run/apiKey/artifact）。 */
  async deleteProject(id: string): Promise<string[]> {
    return this.prisma.$transaction(async (tx) => {
      const arts = await tx.artifact.findMany({ where: { projectId: id }, select: { objectKey: true } })
      await tx.project.delete({ where: { id } })
      return arts.map((a) => a.objectKey)
    })
  }

  /** 删运行：事务内先取关联 artifact objectKey，再 run.delete（DB 级联删 sample/constraint/artifact）。 */
  async deleteRun(id: string): Promise<string[]> {
    return this.prisma.$transaction(async (tx) => {
      const arts = await tx.artifact.findMany({ where: { runId: id }, select: { objectKey: true } })
      await tx.run.delete({ where: { id } })
      return arts.map((a) => a.objectKey)
    })
  }
}

export const adminRepository = new AdminRepository()
