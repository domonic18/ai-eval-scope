/**
 * 超管后台 — 全平台聚合统计（跨租户，只读）。
 * 不复用 BaseRepository（无 requireOrg 门）；先例：ProjectRepository.findByIdAny。
 */
import { Prisma } from "@prisma/client"
import { getPrisma } from "../infra/prisma"

export interface AdminOverview {
  users: { total: number; active: number; disabled: number; admins: number }
  orgs: number
  projects: { total: number; archived: number }
  runs: { total: number; completed: number; failed: number; pending: number }
  samples: number
  artifacts: { total: number; storageBytes: number }
}

export interface AdminTrendPoint {
  run_id: string
  created_at: Date
  DR: number
  CPR: number
  Reward: number
}

class AdminStatsRepository {
  private prisma = getPrisma()

  /** 全平台计数总览。 */
  async overview(): Promise<AdminOverview> {
    const [
      userTotal,
      userActive,
      userDisabled,
      userAdmins,
      orgs,
      projTotal,
      projArchived,
      runTotal,
      runCompleted,
      runFailed,
      runPending,
      samples,
      artTotal,
      artStorage,
    ] = await Promise.all([
      this.prisma.user.count(),
      this.prisma.user.count({ where: { status: "active" } }),
      this.prisma.user.count({ where: { status: "disabled" } }),
      this.prisma.user.count({ where: { role: "admin" } }),
      this.prisma.organization.count(),
      this.prisma.project.count(),
      this.prisma.project.count({ where: { archivedAt: { not: null } } }),
      this.prisma.run.count(),
      this.prisma.run.count({ where: { status: "completed" } }),
      this.prisma.run.count({ where: { status: "failed" } }),
      this.prisma.run.count({ where: { status: { in: ["queued", "running"] } } }),
      this.prisma.sample.count(),
      this.prisma.artifact.count(),
      this.prisma.artifact.aggregate({ _sum: { sizeBytes: true } }),
    ])
    return {
      users: { total: userTotal, active: userActive, disabled: userDisabled, admins: userAdmins },
      orgs,
      projects: { total: projTotal, archived: projArchived },
      runs: { total: runTotal, completed: runCompleted, failed: runFailed, pending: runPending },
      samples,
      artifacts: { total: artTotal, storageBytes: Number(artStorage._sum.sizeBytes ?? 0) },
    }
  }

  /** 全平台 run 指标时序（最近 N 条，按时间升序便于画趋势）。 */
  async trends(opts: { limit?: number; from?: Date } = {}): Promise<AdminTrendPoint[]> {
    const limit = Math.min(500, Math.max(1, opts.limit ?? 100))
    const rows = await this.prisma.$queryRaw<AdminTrendPoint[]>`
      SELECT external_run_id AS run_id, created_at,
             dr AS "DR", cpr AS "CPR", avg_reward AS "Reward"
      FROM runs
      WHERE dr IS NOT NULL
      ${opts.from ? Prisma.sql`AND created_at >= ${opts.from}` : Prisma.empty}
      ORDER BY created_at DESC
      LIMIT ${limit}
    `
    return rows.reverse()
  }

  /** reward 分桶分布（全平台样本）。 */
  async scoreDistribution(): Promise<{ bucket: string; count: number }[]> {
    const rows = await this.prisma.$queryRaw<Array<{ b: number; count: bigint }>>`
      SELECT width_bucket(reward, 0.0, 1.0, 10) AS b, COUNT(*)::bigint AS count
      FROM samples WHERE reward IS NOT NULL
      GROUP BY b ORDER BY b
    `
    return rows.map((r) => ({
      bucket: `${((Number(r.b) - 1) * 0.1).toFixed(1)}–${(Number(r.b) * 0.1).toFixed(1)}`,
      count: Number(r.count),
    }))
  }
}

export const adminStatsRepository = new AdminStatsRepository()
