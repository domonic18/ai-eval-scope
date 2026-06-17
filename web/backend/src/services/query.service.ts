/**
 * Query 业务（§九）。tenant 由中间件注入；只读，隔离由 repository 强制。
 * 制品下载：校验归属后签发 presigned GET（短时效 ≤15min）。
 */

import { PlatformError } from "../middleware/errorHandler";
import { QueryRepository, type RunListFilter } from "../repositories/query.repository";
import { getObjectStorage } from "../infra/objectStorage";
import { getConfig } from "../config";
import type { Tenant } from "../repositories/base.repository";

export interface QueryService {
  dashboard: () => Promise<Awaited<ReturnType<QueryRepository["listProjectsDashboard"]>>>;
  listRuns: (
    projectId: string,
    f: RunListFilter
  ) => Promise<Awaited<ReturnType<QueryRepository["listRuns"]>>>;
  trends: (
    projectId: string,
    f: { from?: Date; to?: Date; limit?: number }
  ) => Promise<Awaited<ReturnType<QueryRepository["trends"]>>>;
  runDetail: (
    projectId: string,
    runId: string
  ) => Promise<NonNullable<Awaited<ReturnType<QueryRepository["runDetail"]>>>>;
  sampleDetail: (
    projectId: string,
    sampleId: string
  ) => Promise<NonNullable<Awaited<ReturnType<QueryRepository["sampleDetail"]>>>>;
  artifactDownload: (artifactId: string) => Promise<{ url: string; contentType: string; filename: string }>;
}

export function createQueryService(tenant: Tenant): QueryService {
  const repo = new QueryRepository(tenant);

  const runDetail: QueryService["runDetail"] = async (projectId, runId) => {
    const r = await repo.runDetail(projectId, runId);
    if (!r) throw new PlatformError("run not found", { status: 404, code: "NOT_FOUND" });
    return r;
  };
  const sampleDetail: QueryService["sampleDetail"] = async (projectId, sampleId) => {
    const s = await repo.sampleDetail(projectId, sampleId);
    if (!s) throw new PlatformError("sample not found", { status: 404, code: "NOT_FOUND" });
    return s;
  };

  async function artifactDownload(artifactId: string) {
    const art = await repo.artifactRef(artifactId);
    if (!art) throw new PlatformError("artifact not found", { status: 404, code: "NOT_FOUND" });
    const storage = getObjectStorage();
    const g = await storage.presignGet({ key: art.objectKey, ttlSec: getConfig().presignTtlSec });
    return {
      url: g.url,
      contentType: art.contentType,
      filename: art.originalName || art.id,
    };
  }

  return {
    dashboard: () => repo.listProjectsDashboard(),
    listRuns: (pid, f) => repo.listRuns(pid, f),
    trends: (pid, f) => repo.trends(pid, f),
    runDetail,
    sampleDetail,
    artifactDownload,
  };
}
