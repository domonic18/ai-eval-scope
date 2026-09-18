/**
 * run 导出数据访问（docs/arch/09 §9.8 导出契约）。
 * 与 query.repository 分离：导出是独立的读模型（全量制品 + 样本聚合），避免 query 膨胀。
 * 隔离同 query：orgId 强制过滤；runId 兼容内部 UUID / external_run_id。
 */

import { BaseRepository, type Tenant } from "./base.repository"

export interface RunExportMeta {
  id: string
  externalRunId: string
  mode: string
  status: string
  totalSamples: number
  scenarioId: string | null
  packageId: string | null
  packageVersion: string | null
  metrics: unknown
  summaryReport: unknown
  failureBreakdown: unknown
  createdAt: Date
  finishedAt: Date | null
}

export interface RunExportSample {
  externalSampleId: string
  status: string
  reward: number | null
  totalDurationMs: number | null
  metrics: unknown
}

export interface RunExportArtifact {
  id: string
  kind: string
  objectKey: string
  contentType: string
  sizeBytes: bigint
  md5: string | null
  originalName: string | null
  sampleExternalId: string | null
}

export class RunExportRepository extends BaseRepository {
  constructor(tenant?: Tenant) {
    super(tenant)
  }

  /** run 元数据（manifest 用）。runId 兼容 UUID / external_run_id；org 强制过滤。 */
  async runMeta(runId: string): Promise<RunExportMeta | null> {
    const orgId = this.requireOrg()
    return this.prisma.run.findFirst({
      where: { project: { orgId }, OR: [{ id: runId }, { externalRunId: runId }] },
      select: {
        id: true,
        externalRunId: true,
        mode: true,
        status: true,
        totalSamples: true,
        scenarioId: true,
        packageId: true,
        packageVersion: true,
        metrics: true,
        summaryReport: true,
        failureBreakdown: true,
        createdAt: true,
        finishedAt: true,
      },
    })
  }

  /** run 下样本聚合（summary 用，指标 JSONB 原样透出）。 */
  async samples(runDbId: string): Promise<RunExportSample[]> {
    return this.prisma.sample.findMany({
      where: { runId: runDbId },
      select: {
        externalSampleId: true,
        status: true,
        reward: true,
        totalDurationMs: true,
        metrics: true,
      },
      orderBy: { externalSampleId: "asc" },
    })
  }

  /** run 下全部制品（含样本逻辑标识，bundle 条目定位用）。按 id 稳定排序保证产出确定性。 */
  async artifacts(runDbId: string): Promise<RunExportArtifact[]> {
    const rows = await this.prisma.artifact.findMany({
      where: { runId: runDbId },
      select: {
        id: true,
        kind: true,
        objectKey: true,
        contentType: true,
        sizeBytes: true,
        md5: true,
        originalName: true,
        sample: { select: { externalSampleId: true } },
      },
      orderBy: { id: "asc" },
    })
    return rows.map((r) => ({ ...r, sampleExternalId: r.sample?.externalSampleId ?? null }))
  }
}
