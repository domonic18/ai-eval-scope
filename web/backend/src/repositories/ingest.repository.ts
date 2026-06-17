/**
 * 摄取数据访问（§7.2）。projectId 作用域；所有写入经调用方传入的事务客户端 tx。
 *
 * - 幂等：tryInsertIngestEvent 写 ingest_events（唯一键 projectId+eventId）；重复抛 P2002，由 service 计 duplicates。
 * - upsert：run/sample 走 DB 唯一键 upsert；constraint/artifact 走应用层 find+写（schema 未加唯一键）。
 * - 依赖解析：resolveRunId / resolveSampleId（缺失返回 null → service 计 DEPENDENCY_MISSING）。
 */

import { Prisma, type PrismaClient } from "@prisma/client";
import { getPrisma } from "../infra/prisma";
import { PlatformError } from "../middleware/errorHandler";
import type {
  RunEventData,
  SampleEventData,
  ConstraintEventData,
  ArtifactEventData,
  DimensionInput,
} from "../schemas/events";

type Tx = Prisma.TransactionClient;

export class DependencyMissingError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = "DependencyMissingError";
  }
}

export class IngestRepository {
  constructor(private readonly projectId: string) {}

  /** 幂等去重插入；重复时抛 Prisma P2002。 */
  async tryInsertIngestEvent(tx: Tx, eventId: string, type: string): Promise<void> {
    await tx.ingestEvent.create({
      data: { projectId: this.projectId, eventId, type },
    });
  }

  async resolveRunId(tx: Tx, externalRunId: string): Promise<string | null> {
    const r = await tx.run.findUnique({
      where: {
        projectId_externalRunId: { projectId: this.projectId, externalRunId },
      },
      select: { id: true },
    });
    return r?.id ?? null;
  }

  async resolveSampleId(tx: Tx, runId: string, externalSampleId: string): Promise<string | null> {
    const s = await tx.sample.findUnique({
      where: { runId_externalSampleId: { runId, externalSampleId } },
      select: { id: true },
    });
    return s?.id ?? null;
  }

  /** run：按 (projectId, externalRunId) upsert。返回 runId。 */
  async upsertRun(tx: Tx, d: RunEventData): Promise<string> {
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
        dr: d.metrics.DR,
        cpr: d.metrics.CPR,
        avgReward: d.metrics.avg_reward,
        condR: d.metrics.condR,
        avgTimeMs: d.metrics.avg_time_ms,
        ruleSetVersion: d.rule_set_version ?? null,
        sutVersion: d.sut_version ?? null,
        failureBreakdown: (d.failure_breakdown ?? undefined) as Prisma.InputJsonValue,
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
        dr: d.metrics.DR,
        cpr: d.metrics.CPR,
        avgReward: d.metrics.avg_reward,
        condR: d.metrics.condR,
        avgTimeMs: d.metrics.avg_time_ms,
        ruleSetVersion: d.rule_set_version ?? null,
        sutVersion: d.sut_version ?? null,
        failureBreakdown: (d.failure_breakdown ?? undefined) as Prisma.InputJsonValue,
        thresholds: (d.thresholds ?? undefined) as Prisma.InputJsonValue,
        langfuseTraceId: d.langfuse_trace_id ?? null,
        langfuseHost: d.langfuse_host ?? null,
        finishedAt: d.finished_at ? new Date(d.finished_at) : null,
      },
      select: { id: true },
    });
    return run.id;
  }

  /** sample：按 (runId, externalSampleId) upsert；写 dimension_scores。返回 sampleId。 */
  async upsertSample(tx: Tx, runId: string, d: SampleEventData): Promise<string> {
    const sample = await tx.sample.upsert({
      where: { runId_externalSampleId: { runId, externalSampleId: d.external_sample_id } },
      create: {
        runId,
        projectId: this.projectId,
        externalSampleId: d.external_sample_id,
        status: d.status ?? "completed",
        sFormat: d.s_format,
        sCommon: d.s_common,
        sSoft: d.s_soft,
        sPref: d.s_pref,
        reward: d.reward,
        totalDurationMs: d.total_duration_ms ?? 0,
        llmCalls: d.llm_calls ?? 0,
        tokenUsage: d.token_usage ?? 0,
      },
      update: {
        status: d.status ?? "completed",
        sFormat: d.s_format,
        sCommon: d.s_common,
        sSoft: d.s_soft,
        sPref: d.s_pref,
        reward: d.reward,
        totalDurationMs: d.total_duration_ms ?? 0,
        llmCalls: d.llm_calls ?? 0,
        tokenUsage: d.token_usage ?? 0,
      },
      select: { id: true },
    });

    if (d.dimensions && d.dimensions.length) {
      // 维度：先清旧（同 sample）再插新，保证幂等
      await tx.dimensionScore.deleteMany({ where: { sampleId: sample.id } });
      await tx.dimensionScore.createMany({
        data: d.dimensions.map((dim: DimensionInput) => ({
          sampleId: sample.id,
          dimensionId: dim.dimension_id,
          name: dim.name,
          weight: dim.weight,
          score: dim.score,
          status: dim.status,
        })),
      });
    }
    return sample.id;
  }

  /** constraint：应用层 upsert（按 sampleId+constraintId），返回 constraintRowId。 */
  async upsertConstraint(tx: Tx, sampleId: string, d: ConstraintEventData): Promise<string> {
    const existing = await tx.constraintResult.findFirst({
      where: { sampleId, constraintId: d.constraint_id },
      select: { id: true },
    });
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
    };
    if (existing) {
      await tx.constraintResult.update({ where: { id: existing.id }, data });
      return existing.id;
    }
    const created = await tx.constraintResult.create({ data: { sampleId, ...data }, select: { id: true } });
    return created.id;
  }

  /** 回填约束的 judge_artifact_id（artifact 事件带 linked_constraint_id 时）。 */
  async linkConstraintArtifact(tx: Tx, sampleId: string, constraintId: string, artifactId: string): Promise<void> {
    await tx.constraintResult.updateMany({
      where: { sampleId, constraintId },
      data: { judgeArtifactId: artifactId },
    });
  }

  /** artifact：按 (runId, objectKey) 去重；存在则返回既有 id，否则创建。 */
  async upsertArtifact(tx: Tx, runId: string, sampleId: string | null, d: ArtifactEventData): Promise<string> {
    const existing = await tx.artifact.findFirst({
      where: { runId, objectKey: d.object_key },
      select: { id: true },
    });
    if (existing) return existing.id;
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
    });
    return created.id;
  }
}

/** 便捷：取单例 PrismaClient（service 用于开启 $transaction）。 */
export function usePrisma(): PrismaClient {
  return getPrisma();
}

export { PlatformError };
