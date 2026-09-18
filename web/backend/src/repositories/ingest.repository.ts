/**
 * 摄取数据访问（§7.2）。projectId 作用域；所有写入经调用方传入的事务客户端 tx。
 *
 * - 幂等：tryInsertIngestEvent 写 ingest_events（唯一键 projectId+eventId）；重复抛 P2002，由 service 计 duplicates。
 * - upsert：run/sample 走 DB 唯一键 upsert；constraint/artifact 走应用层 find+写（schema 未加唯一键）。
 * - 依赖解析：resolveRunId / resolveSampleId（缺失返回 null → service 计 DEPENDENCY_MISSING）。
 */

import { createHash } from "crypto"
import { Prisma, type PrismaClient } from "@prisma/client"
import { getPrisma } from "../infra/prisma"
import { PlatformError } from "../middleware/errorHandler"
import type {
  RunEventData,
  SampleEventData,
  ConstraintEventData,
  ArtifactEventData,
  DimensionInput,
} from "../schemas/events"

type Tx = Prisma.TransactionClient

/** 快照侧 defaults 指纹——与 scenario.repository.hashContent 同约定（"sha256:" + JSON 摘要）。 */
function hashDefaultsContent(content: unknown): string {
  return "sha256:" + createHash("sha256").update(JSON.stringify(content)).digest("hex")
}

export class DependencyMissingError extends Error {
  constructor(msg: string) {
    super(msg)
    this.name = "DependencyMissingError"
  }
}

export class IngestRepository {
  constructor(private readonly projectId: string) {}

  /** 幂等去重插入；重复时抛 Prisma P2002。 */
  async tryInsertIngestEvent(tx: Tx, eventId: string, type: string): Promise<void> {
    await tx.ingestEvent.create({
      data: { projectId: this.projectId, eventId, type },
    })
  }

  async resolveRunId(tx: Tx, externalRunId: string): Promise<string | null> {
    const r = await tx.run.findUnique({
      where: {
        projectId_externalRunId: { projectId: this.projectId, externalRunId },
      },
      select: { id: true },
    })
    return r?.id ?? null
  }

  async resolveSampleId(tx: Tx, runId: string, externalSampleId: string): Promise<string | null> {
    const s = await tx.sample.findUnique({
      where: { runId_externalSampleId: { runId, externalSampleId } },
      select: { id: true },
    })
    return s?.id ?? null
  }

  /**
   * 方向1（arch/09 §7.5 / arch/13 §5.3）：run 事件顺带补缺注册场景资产——只建缺，不动已有。
   *
   * - scenarios 行：不存在才建（name=scenarioId）；文件导入后续可覆盖元数据
   * - defaults（metric_definitions + aggregation_policy）：场景尚无任何 defaults 版本时，
   *   以快照内容建 auto-ingest 版本；已有任一版本则跳过——文件导入为真相源，快照只补缺
   * - P2002（并发撞 (scenarioId, assetId, version) 唯一键）静默吞掉：注册失败不拖垮 run 事件事务
   */
  private async ensureScenarioAssets(
    tx: Tx,
    scenarioId: string,
    snapshot: Record<string, unknown> | null,
  ): Promise<void> {
    try {
      const existing = await tx.scenario.findUnique({
        where: { id: scenarioId },
        select: { id: true },
      })
      if (!existing) {
        // source=auto_ingest：补缺注册的场景仅供可观测，不进配置中心默认视图（arch/09 §7.5）
        await tx.scenario.create({
          data: { id: scenarioId, name: scenarioId, source: "auto_ingest" },
        })
      }
      if (!snapshot) return
      const hasDefaults = await tx.defaultsAsset.findFirst({
        where: { scenarioId, assetId: "default" },
        select: { id: true },
      })
      if (hasDefaults) return
      const content = {
        ...(Array.isArray(snapshot.metric_definitions)
          ? { metric_definitions: snapshot.metric_definitions }
          : {}),
        ...(snapshot.aggregation_policy != null
          ? { aggregation_policy: snapshot.aggregation_policy }
          : {}),
      }
      if (!Object.keys(content).length) return
      await tx.defaultsAsset.create({
        data: {
          scenarioId,
          assetId: "default",
          version:
            (snapshot.package as { version?: string } | undefined)?.version ?? "0.0.0-snapshot",
          labels: ["auto-ingest"],
          content: content as Prisma.InputJsonValue,
          contentHash: hashDefaultsContent(content),
          createdBy: "ingest:auto",
        },
      })
    } catch (e) {
      if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === "P2002") return
      throw e
    }
  }

  /** run：按 (projectId, externalRunId) upsert。返回 runId。 */
  async upsertRun(tx: Tx, d: RunEventData): Promise<string> {
    // 方向1：先补缺注册场景资产（scenarios 行 + defaults 首版本），再落 run
    if (d.scenario_id) {
      await this.ensureScenarioAssets(
        tx,
        d.scenario_id,
        (d.run_config_snapshot ?? null) as Record<string, unknown> | null,
      )
    }
    // Phase 5：inline 运行配置快照 → 建 RunConfigSnapshot 行（按 contentHash 去重），关联 run
    let snapshotId = d.run_config_snapshot_id ?? null
    if (d.run_config_snapshot) {
      const snap = d.run_config_snapshot as Record<string, unknown>
      const contentHash = (snap.snapshot_hash as string) ?? "sha256:unknown"
      const existing = await tx.runConfigSnapshot.findFirst({ where: { contentHash } })
      snapshotId = existing
        ? existing.id
        : (
            await tx.runConfigSnapshot.create({
              data: {
                scenarioId: (snap.scenario_id as string) ?? "",
                packageId: (snap.package as { id?: string })?.id ?? "",
                packageVersion: (snap.package as { version?: string })?.version ?? "",
                content: snap as Prisma.InputJsonValue,
                contentHash,
              },
              select: { id: true },
            })
          ).id
    }
    const run = await tx.run.upsert({
      where: {
        projectId_externalRunId: { projectId: this.projectId, externalRunId: d.external_run_id },
      },
      create: {
        projectId: this.projectId,
        externalRunId: d.external_run_id,
        mode: d.mode,
        status: d.status ?? "completed",
        totalSamples: d.total_samples ?? 0,
        // 场景化：metrics JSONB 为权威
        scenarioId: d.scenario_id ?? null,
        packageId: d.package_id ?? null,
        packageVersion: d.package_version ?? null,
        runConfigSnapshotId: snapshotId,
        metrics: d.metrics as Prisma.InputJsonValue,
        // 遗留一等列：从 metrics 回填（迁移期保留，Phase 5 阶段C 删除）
        ruleSetVersion: d.rule_set_version ?? null,
        sutVersion: d.sut_version ?? null,
        failureBreakdown: (d.failure_breakdown ?? undefined) as Prisma.InputJsonValue,
        summaryReport: (d.summary_report ?? undefined) as Prisma.InputJsonValue,
        thresholds: (d.thresholds ?? undefined) as Prisma.InputJsonValue,
        langfuseTraceId: d.langfuse_trace_id ?? null,
        langfuseHost: d.langfuse_host ?? null,
        createdAt: d.created_at ? new Date(d.created_at) : undefined,
        finishedAt: d.finished_at ? new Date(d.finished_at) : null,
      },
      update: {
        mode: d.mode,
        status: d.status ?? "completed",
        totalSamples: d.total_samples ?? 0,
        summaryReport: (d.summary_report ?? undefined) as Prisma.InputJsonValue,
        scenarioId: d.scenario_id ?? null,
        packageId: d.package_id ?? null,
        packageVersion: d.package_version ?? null,
        runConfigSnapshotId: snapshotId,
        metrics: d.metrics as Prisma.InputJsonValue,
        ruleSetVersion: d.rule_set_version ?? null,
        sutVersion: d.sut_version ?? null,
        failureBreakdown: (d.failure_breakdown ?? undefined) as Prisma.InputJsonValue,
        thresholds: (d.thresholds ?? undefined) as Prisma.InputJsonValue,
        langfuseTraceId: d.langfuse_trace_id ?? null,
        langfuseHost: d.langfuse_host ?? null,
        finishedAt: d.finished_at ? new Date(d.finished_at) : null,
      },
      select: { id: true },
    })
    return run.id
  }

  /** sample：按 (runId, externalSampleId) upsert；写 dimension_scores。返回 sampleId。 */
  async upsertSample(tx: Tx, runId: string, d: SampleEventData): Promise<string> {
    const sample = await tx.sample.upsert({
      where: { runId_externalSampleId: { runId, externalSampleId: d.external_sample_id } },
      create: {
        runId,
        projectId: this.projectId,
        externalSampleId: d.external_sample_id,
        contentHash: d.content_hash ?? null,
        status: d.status ?? "completed",
        metrics: (d.metrics ?? undefined) as Prisma.InputJsonValue,
        reward: d.reward ?? null,
        totalDurationMs: d.total_duration_ms ?? null,
        llmCalls: d.llm_calls ?? 0,
        tokenUsage: d.token_usage ?? 0,
        // run_error 诊断摘要（arch/16 §4.6 合同五）落 extra jsonb
        extra: (d.error_summary
          ? { error_summary: d.error_summary }
          : undefined) as Prisma.InputJsonValue,
      },
      update: {
        contentHash: d.content_hash ?? null,
        status: d.status ?? "completed",
        metrics: (d.metrics ?? undefined) as Prisma.InputJsonValue,
        reward: d.reward ?? null,
        totalDurationMs: d.total_duration_ms ?? null,
        llmCalls: d.llm_calls ?? 0,
        tokenUsage: d.token_usage ?? 0,
        extra: (d.error_summary
          ? { error_summary: d.error_summary }
          : undefined) as Prisma.InputJsonValue,
      },
      select: { id: true },
    })

    if (d.dimensions && d.dimensions.length) {
      // 维度：先清旧（同 sample）再插新，保证幂等
      await tx.dimensionScore.deleteMany({ where: { sampleId: sample.id } })
      await tx.dimensionScore.createMany({
        data: d.dimensions.map((dim: DimensionInput) => ({
          sampleId: sample.id,
          dimensionId: dim.dimension_id,
          name: dim.name,
          weight: dim.weight,
          score: dim.score,
          status: dim.status,
        })),
      })
    }
    return sample.id
  }

  /** constraint：应用层 upsert（按 sampleId+constraintId），返回 constraintRowId。 */
  async upsertConstraint(tx: Tx, sampleId: string, d: ConstraintEventData): Promise<string> {
    const existing = await tx.constraintResult.findFirst({
      where: { sampleId, constraintId: d.constraint_id },
      select: { id: true },
    })
    const data = {
      projectId: this.projectId,
      constraintId: d.constraint_id,
      ruleId: d.rule_id ?? null,
      name: d.name,
      tier: d.tier,
      status: d.status,
      passed: d.passed,
      score: d.score,
      rawScore: d.raw_score ?? null,
      reason: d.reason,
      durationMs: d.duration_ms,
      judgeProvider: d.judge_provider ?? null,
      judgeModel: d.judge_model ?? null,
      details: (d.details ?? undefined) as Prisma.InputJsonValue,
      moduleResults: (d.module_results ?? undefined) as Prisma.InputJsonValue,
    }
    if (existing) {
      await tx.constraintResult.update({ where: { id: existing.id }, data })
      return existing.id
    }
    const created = await tx.constraintResult.create({
      data: { sampleId, ...data },
      select: { id: true },
    })
    return created.id
  }

  /** 回填约束的 judge_artifact_id（artifact 事件带 linked_constraint_id 时）。 */
  async linkConstraintArtifact(
    tx: Tx,
    sampleId: string,
    constraintId: string,
    artifactId: string,
  ): Promise<void> {
    await tx.constraintResult.updateMany({
      where: { sampleId, constraintId },
      data: { judgeArtifactId: artifactId },
    })
  }

  /** artifact：按 (runId, objectKey) 去重；存在则返回既有 id，否则创建。 */
  async upsertArtifact(
    tx: Tx,
    runId: string,
    sampleId: string | null,
    d: ArtifactEventData,
  ): Promise<string> {
    const existing = await tx.artifact.findFirst({
      where: { runId, objectKey: d.object_key },
      select: { id: true },
    })
    if (existing) return existing.id
    const created = await tx.artifact.create({
      data: {
        projectId: this.projectId,
        runId,
        sampleId,
        kind: d.kind,
        objectKey: d.object_key,
        storage: "minio", // 由调用方/部署决定；此处记默认，可按 cfg 扩展
        contentType: d.content_type,
        sizeBytes: BigInt(d.size_bytes),
        md5: d.md5 ?? null,
        originalName: d.original_name ?? null,
      },
      select: { id: true },
    })
    return created.id
  }
}

/** 便捷：取单例 PrismaClient（service 用于开启 $transaction）。 */
export function usePrisma(): PrismaClient {
  return getPrisma()
}

export { PlatformError }
