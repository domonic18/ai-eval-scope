/**
 * Query 业务（§九）。tenant 由中间件注入；只读，隔离由 repository 强制。
 * 制品元信息：校验归属后返回 objectKey/contentType/filename（URL 签发交由路由层）。
 */

import { PlatformError } from "../middleware/errorHandler"
import { getLogger } from "../infra/logger"
import { getObjectStorage } from "../infra/objectStorage"
import { AuditService } from "./audit.service"
import { QueryRepository, type RunListFilter } from "../repositories/query.repository"
import type { Tenant } from "../repositories/base.repository"

export interface QueryService {
  dashboard: () => Promise<Awaited<ReturnType<QueryRepository["listProjectsDashboard"]>>>
  listRuns: (
    projectId: string,
    f: RunListFilter,
  ) => Promise<Awaited<ReturnType<QueryRepository["listRuns"]>>>
  trends: (
    projectId: string,
    f: { from?: Date; to?: Date; limit?: number },
  ) => Promise<Awaited<ReturnType<QueryRepository["trends"]>>>
  runDetail: (
    projectId: string,
    runId: string,
  ) => Promise<
    NonNullable<Awaited<ReturnType<QueryRepository["runDetail"]>>> & { canDelete: boolean }
  >
  sampleDetail: (
    projectId: string,
    sampleId: string,
  ) => Promise<NonNullable<Awaited<ReturnType<QueryRepository["sampleDetail"]>>>>
  artifactMeta: (
    artifactId: string,
  ) => Promise<{ objectKey: string; contentType: string; filename: string }>
  deleteRun: (runId: string) => Promise<void>
  samples: (projectId: string) => Promise<
    Awaited<ReturnType<QueryRepository["listSamplesByProject"]>>
  >
  sampleTrends: (
    projectId: string,
    externalSampleId: string,
    limit?: number,
  ) => Promise<Awaited<ReturnType<QueryRepository["sampleTrends"]>>>
}

export function createQueryService(tenant: Tenant): QueryService {
  const repo = new QueryRepository(tenant)

  const runDetail: QueryService["runDetail"] = async (projectId, runId) => {
    const r = await repo.runDetail(projectId, runId)
    if (!r) throw new PlatformError("run not found", { status: 404, code: "NOT_FOUND" })
    return { ...r, canDelete: tenant.role === "owner" }
  }
  const sampleDetail: QueryService["sampleDetail"] = async (projectId, sampleId) => {
    const s = await repo.sampleDetail(projectId, sampleId)
    if (!s) throw new PlatformError("sample not found", { status: 404, code: "NOT_FOUND" })
    return s
  }

  async function artifactMeta(artifactId: string) {
    const art = await repo.artifactRef(artifactId)
    if (!art) throw new PlatformError("artifact not found", { status: 404, code: "NOT_FOUND" })
    return {
      objectKey: art.objectKey,
      contentType: art.contentType,
      filename: art.originalName || art.id,
    }
  }

  const deleteRun: QueryService["deleteRun"] = async (runId) => {
    // 先取 run 元信息（校验存在性 + 归属 + 审计 metadata），再删
    const run = await repo.runDetail(tenant.projectId!, runId)
    if (!run) throw new PlatformError("run not found", { status: 404, code: "NOT_FOUND" })
    const objectKeys = await repo.deleteRun(runId)
    // 对象存储清理：best-effort，失败仅 warn（DB 已删、走势以 DB 为准）
    if (objectKeys.length) {
      try {
        await getObjectStorage().deleteObjects(objectKeys)
      } catch (err) {
        getLogger().warn(
          { runId, count: objectKeys.length, error: (err as Error).message },
          "run_delete_objects_failed",
        )
      }
    }
    await AuditService.log({
      actorUserId: tenant.userId,
      orgId: tenant.orgId,
      action: "run.delete",
      targetType: "run",
      targetId: runId,
      metadata: { projectId: tenant.projectId, externalRunId: run.externalRunId },
    })
  }

  return {
    dashboard: () => repo.listProjectsDashboard(),
    listRuns: (pid, f) => repo.listRuns(pid, f),
    trends: (pid, f) => repo.trends(pid, f),
    runDetail,
    sampleDetail,
    artifactMeta,
    deleteRun,
    samples: (pid) => repo.listSamplesByProject(pid),
    sampleTrends: (pid, sid, limit) =>
      repo.sampleTrends(pid, sid, Math.min(500, Math.max(1, limit ?? 100))),
  }
}
