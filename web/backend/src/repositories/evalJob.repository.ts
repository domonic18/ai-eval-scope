/**
 * EvalJob 数据访问（public.eval_jobs，与 executor 共享）。
 *
 * - Web 写入（queued）+ 查询；executor 更新状态机（running/completed/failed）。
 * - 查询强制 projectId 租户过滤（提交者只能看自己 Key 所属项目的 job）。
 */

import { EvalJob } from "@prisma/client"
import { BaseRepository, type Tenant } from "./base.repository"

export interface EvalJobCreateInput {
  jobId: string
  projectId: string
  orgId: string
  apiKeyId: string
  inputKind: string
  scope: string
  inputObjectKey: string
  inputPresignedUrl: string
  ruleSetId: string
  packageRef?: string | null
  taskId?: string | null
  taskTitle?: string | null
  taskSubject?: string | null
}

class EvalJobRepository extends BaseRepository {
  constructor(tenant?: Tenant) {
    super(tenant)
  }

  create(data: EvalJobCreateInput): Promise<EvalJob> {
    // Prisma model 字段名为 id（@map job_id），其余 camelCase 字段名一致
    const { jobId, ...rest } = data
    return this.prisma.evalJob.create({ data: { id: jobId, ...rest } })
  }

  /** 查询（强制 projectId 租户过滤）。 */
  findById(jobId: string): Promise<EvalJob | null> {
    const projectId = this.tenant.projectId
    return this.prisma.evalJob.findFirst({ where: { id: jobId, projectId } })
  }

  /** 回填 SCF RequestId（链路追踪）。 */
  async updateScfRequestId(jobId: string, scfRequestId: string): Promise<number> {
    const r = await this.prisma.evalJob.updateMany({
      where: { id: jobId },
      data: { scfRequestId },
    })
    return r.count
  }
}

export { EvalJobRepository }
