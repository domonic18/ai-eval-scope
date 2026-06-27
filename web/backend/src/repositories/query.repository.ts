/**
 * Query 数据访问（§九）。projectId 作用域；只读，强制租户过滤。
 *
 * - 项目看板：listProjectsDashboard（每项目最新运行指标 + 运行总数，一条 SQL）。
 * - 运行列表/趋势/详情、样本详情、制品下载引用。
 */

import { Prisma } from "@prisma/client"
import { BaseRepository, type Tenant } from "./base.repository"

export interface RunListFilter {
  mode?: string
  ruleSetVersion?: string
  from?: Date
  to?: Date
  order?: "asc" | "desc"
  page?: number
  size?: number
}

export interface TrendPoint {
  run_id: string
  created_at: Date
  DR: number
  CPR: number
  Reward: number
}

class QueryRepository extends BaseRepository {
  constructor(tenant?: Tenant) {
    super(tenant)
  }

  /** 项目看板：每项目最新运行的指标 + 运行总数。 */
  async listProjectsDashboard() {
    const orgId = this.requireOrg()
    // 每项目最新运行用 distinct on（PostgreSQL）；Prisma 无原生支持，走 $queryRaw。
    const rows = await this.prisma.$queryRaw<
      Array<{
        id: string
        name: string
        slug: string
        description: string | null
        archived_at: Date | null
        created_at: Date
        run_count: bigint
        latest_run_id: string | null
        latest_created_at: Date | null
        dr: number | null
        cpr: number | null
        avg_reward: number | null
        owner_name: string | null
      }>
    >(Prisma.sql`
      SELECT p.id, p.name, p.slug, p.description, p.archived_at, p.created_at,
             COALESCE(r_cnt.run_count, 0)::bigint AS run_count,
             lr.latest_run_id, lr.latest_created_at, lr.dr, lr.cpr, lr.avg_reward,
             COALESCE(u.name, u.email) AS owner_name
      FROM projects p
      LEFT JOIN users u ON u.id = p.created_by
      LEFT JOIN (
        SELECT project_id, COUNT(*)::bigint AS run_count FROM runs GROUP BY project_id
      ) r_cnt ON r_cnt.project_id = p.id
      LEFT JOIN LATERAL (
        SELECT id AS latest_run_id, created_at AS latest_created_at, dr, cpr, avg_reward
        FROM runs WHERE project_id = p.id ORDER BY created_at DESC LIMIT 1
      ) lr ON true
      WHERE p.org_id = ${orgId} AND p.archived_at IS NULL
      ORDER BY p.created_at DESC
    `)
    return rows.map((r) => ({
      id: r.id,
      name: r.name,
      slug: r.slug,
      description: r.description,
      createdAt: r.created_at,
      runCount: Number(r.run_count),
      latestRun: r.latest_run_id
        ? {
            runId: r.latest_run_id,
            createdAt: r.latest_created_at,
            dr: r.dr,
            cpr: r.cpr,
            avgReward: r.avg_reward,
          }
        : null,
      ownerName: r.owner_name,
    }))
  }

  /** 运行列表（过滤 + 分页）。 */
  async listRuns(projectId: string, f: RunListFilter) {
    const orgId = this.requireOrg()
    const where: Prisma.RunWhereInput = { projectId, project: { orgId } }
    if (f.mode) where.mode = f.mode
    if (f.ruleSetVersion) where.ruleSetVersion = f.ruleSetVersion
    const createdAt: Prisma.DateTimeFilter<"Run"> = {}
    if (f.from) createdAt.gte = f.from
    if (f.to) createdAt.lte = f.to
    if (f.from || f.to) where.createdAt = createdAt

    const page = Math.max(1, f.page ?? 1)
    const size = Math.min(200, Math.max(1, f.size ?? 50))
    const [items, total] = await Promise.all([
      this.prisma.run.findMany({
        where,
        orderBy: { createdAt: f.order === "asc" ? "asc" : "desc" },
        skip: (page - 1) * size,
        take: size,
      }),
      this.prisma.run.count({ where }),
    ])
    return { items, total, page, size }
  }

  /** 趋势聚合（核心指标已为一等列，走索引）。 */
  async trends(projectId: string, f: { from?: Date; to?: Date; limit?: number }) {
    const orgId = this.requireOrg()
    const limit = Math.min(500, Math.max(1, f.limit ?? 100))
    return this.prisma.$queryRaw<TrendPoint[]>`
      SELECT external_run_id AS run_id, created_at,
             dr AS "DR", cpr AS "CPR", avg_reward AS "Reward"
      FROM runs
      WHERE project_id = ${projectId}
        AND project_id IN (SELECT id FROM projects WHERE org_id = ${orgId})
        ${f.from ? Prisma.sql`AND created_at >= ${f.from}` : Prisma.empty}
        ${f.to ? Prisma.sql`AND created_at <= ${f.to}` : Prisma.empty}
      ORDER BY created_at ASC
      LIMIT ${limit}
    `
  }

  /** 运行详情（含样本摘要）。 */
  async runDetail(projectId: string, runId: string) {
    const orgId = this.requireOrg()
    const run = await this.prisma.run.findFirst({
      where: { id: runId, projectId, project: { orgId } },
      include: {
        samples: {
          orderBy: { externalSampleId: "asc" },
          select: {
            id: true,
            externalSampleId: true,
            status: true,
            reward: true,
            sFormat: true,
            sCommon: true,
            sSoft: true,
            sPref: true,
          },
        },
      },
    })
    return run
  }

  /** 样本详情（含约束 + 制品引用）。 */
  async sampleDetail(projectId: string, sampleId: string) {
    const orgId = this.requireOrg()
    return this.prisma.sample.findFirst({
      where: { id: sampleId, projectId, run: { project: { orgId } } },
      include: {
        constraintResults: { orderBy: { tier: "asc" } },
        artifacts: {
          select: { id: true, kind: true, contentType: true, sizeBytes: true, originalName: true },
        },
      },
    })
  }

  /** 制品下载引用（校验归属后返回对象 key + 元信息）。 */
  async artifactRef(artifactId: string) {
    const orgId = this.requireOrg()
    return this.prisma.artifact.findFirst({
      where: { id: artifactId, project: { orgId } },
      select: { id: true, objectKey: true, contentType: true, originalName: true, kind: true },
    })
  }

  /**
   * 删除运行：事务内先取该 run 全部制品的 objectKey，再 run.delete
   * （DB 级联自动删 samples/constraint_results/artifacts 行）。返回待清理的 objectKeys。
   * 归属由 runGuard 校验，此处信任 runId。
   */
  async deleteRun(runId: string): Promise<string[]> {
    return this.prisma.$transaction(async (tx) => {
      const arts = await tx.artifact.findMany({
        where: { runId },
        select: { objectKey: true },
      })
      await tx.run.delete({ where: { id: runId } })
      return arts.map((a) => a.objectKey)
    })
  }
}

export { QueryRepository }
