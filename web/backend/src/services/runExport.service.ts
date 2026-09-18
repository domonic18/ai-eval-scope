/**
 * run 导出契约（docs/arch/09 §9.8）：run → 自描述 bundle（流式 zip）。
 *
 * - 自描述：manifest.json 为机器可读索引（run 元数据 + metrics + summary_report +
 *   entries[path/kind/sample_id/size_bytes/md5]），bundle 可审计可重建，UI 只是触发器。
 * - 结构即协议：summary.{md,json} + run/{kind}/（无样本归属）+
 *   samples/{externalSampleId}/{kind}/（transcript.md 置样本根）。
 * - 确定性：条目按 样本→kind→名 排序、id 稳定排序，同名去重加 id 前缀。
 * - 内存边界：逐对象取 Buffer（峰值 ≈ 最大单对象）；超 PLATFORM_MAX_EXPORT_BYTES 写头前 413。
 */

import archiver from "archiver"
import { PlatformError } from "../middleware/errorHandler"
import { getLogger } from "../infra/logger"
import { getObjectStorage } from "../infra/objectStorage"
import { getConfig } from "../config"
import { RunExportRepository, type RunExportMeta } from "../repositories/runExport.repository"
import type { Tenant } from "../repositories/base.repository"

const log = getLogger()

interface BundleEntry {
  path: string
  kind: string
  sample_id: string | null
  size_bytes: number
  md5: string | null
}

/** 条目名清洗：`\`→`/`、去空段/`.`/`..` 段（防路径穿越），空名兜底。 */
export function safeEntryName(raw: string): string {
  const cleaned = raw
    .replace(/[^\P{C}]/gu, "")
    .replace(/\\/g, "/")
    .split("/")
    .filter((p) => p && p !== "." && p !== "..")
    .join("/")
  return cleaned || "unnamed"
}

function zipFilename(externalRunId: string): string {
  const safe = externalRunId.replace(/[^\w.-]/g, "_")
  return `run-${safe}.zip`
}

function buildSummaryMd(meta: RunExportMeta, samplesJson: unknown): string {
  const lines: string[] = [
    `# 运行报告 ${meta.externalRunId}`,
    "",
    `- 场景：${meta.scenarioId ?? "—"}`,
    `- 包：${meta.packageId ?? "—"}${meta.packageVersion ? ` @ ${meta.packageVersion}` : ""}`,
    `- 模式：${meta.mode} · 状态：${meta.status}`,
    `- 样本数：${meta.totalSamples}`,
    `- 创建：${meta.createdAt.toISOString()}${meta.finishedAt ? ` · 结束：${meta.finishedAt.toISOString()}` : ""}`,
    "",
    "## 指标",
    "",
  ]
  const metrics = (meta.metrics ?? {}) as Record<string, number>
  const keys = Object.keys(metrics)
  if (keys.length) {
    lines.push("| 指标 | 值 |", "|---|---|")
    for (const k of keys) lines.push(`| ${k} | ${metrics[k]} |`)
  } else {
    lines.push("（无运行级指标）")
  }
  lines.push("", `## 样本（${Array.isArray(samplesJson) ? samplesJson.length : 0}）`, "")
  const arr = Array.isArray(samplesJson) ? (samplesJson as Array<Record<string, unknown>>) : []
  if (arr.length) {
    lines.push("| 样本 | 状态 | reward |", "|---|---|---|")
    for (const s of arr) lines.push(`| ${s.externalSampleId} | ${s.status} | ${s.reward ?? "—"} |`)
  }
  const report = meta.summaryReport
  if (report != null) {
    lines.push("", "## 评估摘要报告", "", "```json", JSON.stringify(report, null, 2), "```")
  }
  lines.push("")
  return lines.join("\n")
}

export function createRunExportService(tenant: Tenant) {
  const repo = new RunExportRepository(tenant)

  /**
   * 构建 run 导出 bundle。返回 zip 流与文件名；404/413 在写响应头前抛出。
   * 流中对象缺失 → skip + warn（bundle 记录实际成功条目，manifest 始终与内容一致）。
   */
  async function buildExport(runId: string): Promise<{ filename: string; stream: archiver.Archiver }> {
    const meta = await repo.runMeta(runId)
    if (!meta) throw new PlatformError("run not found", { status: 404, code: "NOT_FOUND" })

    const [samples, artifacts] = await Promise.all([repo.samples(meta.id), repo.artifacts(meta.id)])

    // 体积护栏（BigInt 求和仅作护栏，不进 JSON）
    const total = artifacts.reduce((acc, a) => acc + a.sizeBytes, 0n)
    if (total > BigInt(getConfig().maxExportBytes)) {
      throw new PlatformError(
        `export bundle too large: ${total} bytes (limit ${getConfig().maxExportBytes})`,
        { status: 413, code: "PAYLOAD_TOO_LARGE" },
      )
    }

    // 条目路径分配（确定性 + 去重）
    const seen = new Set<string>()
    const planned: Array<{ artifact: (typeof artifacts)[number]; path: string }> = []
    for (const a of artifacts) {
      const base = a.originalName ? safeEntryName(a.originalName) : a.id
      let path =
        a.sampleExternalId == null
          ? `run/${a.kind}/${base}`
          : a.kind === "transcript"
            ? `samples/${safeEntryName(a.sampleExternalId)}/${base}`
            : `samples/${safeEntryName(a.sampleExternalId)}/${a.kind}/${base}`
      if (seen.has(path)) {
        // 同目录同名：加制品 id 消歧（id 全局唯一，循环一轮必终止）
        while (seen.has(path)) {
          const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/") + 1) : ""
          const name = path.slice(dir.length)
          const dot = name.lastIndexOf(".")
          const stem = dot > 0 ? name.slice(0, dot) : name
          const ext = dot > 0 ? name.slice(dot) : ""
          path = `${dir}${stem}-${a.id}${ext}`
        }
      }
      seen.add(path)
      planned.push({ artifact: a, path })
    }

    const storage = getObjectStorage()
    const archive = archiver("zip", { zlib: { level: 6 } })
    const entries: BundleEntry[] = []

    for (const { artifact: a, path } of planned) {
      try {
        const buf = await storage.get({ key: a.objectKey })
        archive.append(buf, { name: path })
        entries.push({
          path,
          kind: a.kind,
          sample_id: a.sampleExternalId,
          size_bytes: Number(a.sizeBytes),
          md5: a.md5,
        })
      } catch (err) {
        log.warn(
          { runId: meta.id, objectKey: a.objectKey, error: (err as Error).message },
          "run_export_object_skipped",
        )
      }
    }

    // summary.json：样本聚合（结构化，机器可读）
    const summaryJson = {
      run: {
        external_run_id: meta.externalRunId,
        mode: meta.mode,
        status: meta.status,
        total_samples: meta.totalSamples,
        scenario_id: meta.scenarioId,
        package_id: meta.packageId,
        package_version: meta.packageVersion,
        created_at: meta.createdAt.toISOString(),
        finished_at: meta.finishedAt?.toISOString() ?? null,
        metrics: meta.metrics,
        failure_breakdown: meta.failureBreakdown,
      },
      samples,
    }
    archive.append(Buffer.from(JSON.stringify(summaryJson, null, 2), "utf8"), {
      name: "summary.json",
    })
    archive.append(Buffer.from(buildSummaryMd(meta, samples), "utf8"), { name: "summary.md" })

    // manifest.json：自描述索引（最后组装 → entries 与实际入包内容一致）
    const manifest = {
      schema: "run-export/v1",
      run: summaryJson.run,
      summary_report: meta.summaryReport,
      entry_count: entries.length,
      entries,
    }
    archive.append(Buffer.from(JSON.stringify(manifest, null, 2), "utf8"), { name: "manifest.json" })

    void archive.finalize().catch((err: Error) => archive.emit("error", err))
    return { filename: zipFilename(meta.externalRunId), stream: archive }
  }

  return { buildExport }
}
