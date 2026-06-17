/**
 * 摄取业务编排（§7.2 / §7.5）。
 *
 * 流程：
 *  1. schema_version 兼容校验（不兼容 → SCHEMA_VERSION_UNSUPPORTED 400）。
 *  2. envelope 结构校验（非法 → SCHEMA_INVALID 400）。
 *  3. project_id 跨项目拒绝（与 Key 所属项目不一致 → PROJECT_FORBIDDEN 403）。
 *  4. 逐事件 schema 校验（非法 → 计 errors[]，不影响合法事件）。
 *  5. 逐事件事务：先写 ingest_events 幂等键（重复抛 P2002 → duplicates），
 *     再按 type 路由 upsert（依赖缺失 → DEPENDENCY_MISSING，回滚不消费 event_id，可重试）。
 *  6. artifact 事件：事务前 HEAD 校验对象存在。
 *  7. 返回 202 { accepted, duplicates, errors }（部分接受）。
 *
 * upsert + 去重表 = at-least-once 投递下的精确一次生效。
 */

import { Prisma } from "@prisma/client";
import { IngestRepository, DependencyMissingError, usePrisma } from "../repositories/ingest.repository";
import { getObjectStorage } from "../infra/objectStorage";
import { getLogger } from "../infra/logger";
import {
  validateEnvelope,
  validateEvent,
  SUPPORTED_SCHEMA_VERSION,
} from "../schemas/validate";
import type { IngestBatch, IngestEvent } from "../schemas/events";
import type { Tenant } from "../repositories/base.repository";

export interface IngestEventError {
  event_id: string;
  code: string;
  message: string;
}

export interface IngestResult {
  accepted: number;
  duplicates: number;
  errors: IngestEventError[];
}

export type IngestOutcome =
  | { status: "accepted"; result: IngestResult } // HTTP 202
  | { status: "version_unsupported"; got: string } // HTTP 400
  | { status: "forbidden" } // HTTP 403
  | { status: "schema_invalid"; problems: { path: string; message: string }[] }; // HTTP 400

export async function ingest(tenant: Tenant, body: unknown): Promise<IngestOutcome> {
  // 1. schema_version 兼容
  if (body && typeof body === "object" && "schema_version" in body) {
    const v = (body as { schema_version?: unknown }).schema_version;
    if (typeof v === "string" && v !== SUPPORTED_SCHEMA_VERSION) {
      return { status: "version_unsupported", got: v };
    }
  }

  // 2. envelope 结构校验
  const envelope = validateEnvelope(body);
  if (!envelope.ok) {
    return { status: "schema_invalid", problems: envelope.problems };
  }
  const batch = body as IngestBatch;

  // 3. 跨项目拒绝
  const effectiveProjectId = tenant.projectId!;
  if (batch.project_id && batch.project_id !== effectiveProjectId) {
    return { status: "forbidden" };
  }

  const prisma = usePrisma();
  const repo = new IngestRepository(effectiveProjectId);
  const storage = getObjectStorage();
  const logger = getLogger();

  const result: IngestResult = { accepted: 0, duplicates: 0, errors: [] };

  for (const ev of batch.events) {
    const eventId = ev.event_id ?? "(missing)";

    // 4. 逐事件 schema 校验
    const evCheck = validateEvent(ev);
    if (!evCheck.ok) {
      result.errors.push({
        event_id: eventId,
        code: "SCHEMA_INVALID",
        message: evCheck.problems.map((p) => `${p.path}: ${p.message}`).join("; "),
      });
      continue;
    }

    // 5. artifact：事务前 HEAD 校验对象存在
    if (ev.type === "artifact") {
      const head = await storage.head({ key: ev.data.object_key }).catch(() => null);
      if (!head) {
        result.errors.push({
          event_id: eventId,
          code: "DEPENDENCY_MISSING",
          message: `artifact object not found: ${ev.data.object_key}`,
        });
        continue;
      }
    }

    // 6. 逐事件事务：幂等键 → 业务 upsert
    try {
      await prisma.$transaction(async (tx) => {
        await repo.tryInsertIngestEvent(tx, ev.event_id, ev.type);
        await routeEvent(tx, repo, ev);
      });
      result.accepted += 1;
    } catch (err) {
      const e = err as { code?: string; name?: string; message?: string };
      if (e.code === "P2002") {
        // 幂等键冲突 → 重复事件（业务写入随事务回滚）
        result.duplicates += 1;
      } else if (e.name === "DependencyMissingError" || e instanceof DependencyMissingError) {
        result.errors.push({
          event_id: eventId,
          code: "DEPENDENCY_MISSING",
          message: e.message || "dependency not found",
        });
      } else {
        logger.error({ event_id: eventId, error: e.message }, "ingest_event_failed");
        result.errors.push({
          event_id: eventId,
          code: "INTERNAL",
          message: e.message || "internal error",
        });
      }
    }
  }

  return { status: "accepted", result };
}

/** 按 type 路由到 repository upsert（依赖缺失抛 DependencyMissingError）。 */
async function routeEvent(tx: Prisma.TransactionClient, repo: IngestRepository, ev: IngestEvent): Promise<void> {
  switch (ev.type) {
    case "run": {
      await repo.upsertRun(tx, ev.data);
      return;
    }
    case "sample": {
      const d = ev.data;
      const runId = await repo.resolveRunId(tx, d.external_run_id);
      if (!runId) throw new DependencyMissingError(`run not found: ${d.external_run_id}`);
      await repo.upsertSample(tx, runId, d);
      return;
    }
    case "constraint": {
      const d = ev.data;
      const runId = await repo.resolveRunId(tx, d.external_run_id);
      const sampleId = runId ? await repo.resolveSampleId(tx, runId, d.external_sample_id) : null;
      if (!runId || !sampleId) {
        throw new DependencyMissingError(`sample not found: ${d.external_run_id}/${d.external_sample_id}`);
      }
      await repo.upsertConstraint(tx, sampleId, d);
      return;
    }
    case "artifact": {
      const d = ev.data;
      const runId = await repo.resolveRunId(tx, d.external_run_id);
      if (!runId) throw new DependencyMissingError(`run not found: ${d.external_run_id}`);
      const sampleId = d.external_sample_id
        ? await repo.resolveSampleId(tx, runId, d.external_sample_id)
        : null;
      const artifactId = await repo.upsertArtifact(tx, runId, sampleId, d);
      if (d.linked_constraint_id && sampleId) {
        await repo.linkConstraintArtifact(tx, sampleId, d.linked_constraint_id, artifactId);
      }
      return;
    }
  }
}
