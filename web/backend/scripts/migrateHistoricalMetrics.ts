/**
 * 一次性历史指标迁移（Phase 3，对齐 09 §9.5.6 / §11.3 阶段B）。
 *
 * 把存量 Run/Sample 的遗留一等指标列（dr/cpr/avg_reward/...、s_format/...）回填到
 * metrics JSONB，并为每条 Run 关联 courseware 默认 RunConfigSnapshot。无前端 fallback：
 * 迁移完成后所有历史 Run 均具备完整场景化 metrics + 快照，前端可彻底动态渲染。
 *
 * 幂等：仅处理 metrics 为空的行，可安全重跑。
 *
 * 用法：npx tsx scripts/migrateHistoricalMetrics.ts   （读 PLATFORM_DATABASE_URL）
 */

import { createHash } from "crypto"
import { Prisma, type PrismaClient } from "@prisma/client"
import {
  COURSEWARE_DEFAULT_METRIC_DEFS,
  COURSEWARE_DEFAULT_AGGREGATION_POLICY,
} from "../src/config/coursewareDefaults"

// 单一源（src/config/coursewareDefaults.ts），本脚本与 import 脚本共用
const COURSEWARE_METRIC_DEFINITIONS = COURSEWARE_DEFAULT_METRIC_DEFS
const COURSEWARE_AGGREGATION_POLICY = COURSEWARE_DEFAULT_AGGREGATION_POLICY

export interface MigrationResult {
  scenarioId: string
  snapshotId: string
  runsUpdated: number
  samplesUpdated: number
}

/** 执行一次性历史指标迁移。幂等（仅处理 metrics 为空的行）。 */
export async function migrateHistoricalMetrics(prisma: PrismaClient): Promise<MigrationResult> {
  // 1. 确保 courseware 场景存在
  await prisma.scenario.upsert({
    where: { id: "courseware" },
    update: {},
    create: { id: "courseware", name: "课件质量评估", description: "课件生成场景默认包" },
  })

  // 2. 找到/创建 courseware 默认 RunConfigSnapshot（按 content_hash 去重）
  const content = {
    scenario_id: "courseware",
    package: { id: "courseware", version: "1.0.0" },
    aggregation_policy: COURSEWARE_AGGREGATION_POLICY,
    metric_definitions: COURSEWARE_METRIC_DEFINITIONS,
  }
  const contentHash = "sha256:" + createHash("sha256").update(JSON.stringify(content)).digest("hex")
  const snapshot = await prisma.runConfigSnapshot.findFirst({ where: { contentHash } })
  const snapshotId = snapshot
    ? snapshot.id
    : (
        await prisma.runConfigSnapshot.create({
          data: {
            scenarioId: "courseware",
            packageId: "courseware",
            packageVersion: "1.0.0",
            content: content as unknown as Prisma.InputJsonValue,
            contentHash,
          },
          select: { id: true },
        })
      ).id

  // 3. 回填 Run.metrics（仅 metrics 为 DB NULL 的 Run）
  const runs = await prisma.run.findMany({
    where: { metrics: { equals: Prisma.DbNull } },
    select: { id: true, dr: true, cpr: true, avgReward: true, avgSoft: true, avgPref: true, condR: true },
  })
  let runsUpdated = 0
  for (const r of runs) {
    const m: Record<string, number> = {}
    if (r.dr != null) m["courseware:document_rate"] = r.dr
    if (r.cpr != null) m["courseware:constraint_pass_rate"] = r.cpr
    if (r.avgReward != null) m["courseware:reward"] = r.avgReward
    if (r.avgSoft != null) m["courseware:soft"] = r.avgSoft
    if (r.avgPref != null) m["courseware:pref"] = r.avgPref
    if (r.condR != null) m["courseware:conditional_reward"] = r.condR
    if (Object.keys(m).length === 0) continue // 无任何遗留指标，跳过
    await prisma.run.update({
      where: { id: r.id },
      data: {
        metrics: m,
        scenarioId: "courseware",
        packageId: "courseware",
        packageVersion: "1.0.0",
        runConfigSnapshotId: snapshotId,
      },
    })
    runsUpdated++
  }

  // 4. 回填 Sample.metrics（仅 metrics 为 DB NULL 的 Sample）
  const samples = await prisma.sample.findMany({
    where: { metrics: { equals: Prisma.DbNull } },
    select: { id: true, reward: true, sSoft: true, sPref: true, sFormat: true, sCommon: true },
  })
  let samplesUpdated = 0
  for (const s of samples) {
    const m: Record<string, number> = {}
    if (s.reward != null) m["reward"] = s.reward
    if (s.sSoft != null) m["soft"] = s.sSoft
    if (s.sPref != null) m["pref"] = s.sPref
    if (s.sFormat != null) m["format"] = s.sFormat
    if (s.sCommon != null) m["common"] = s.sCommon
    if (Object.keys(m).length === 0) continue
    await prisma.sample.update({ where: { id: s.id }, data: { metrics: m } })
    samplesUpdated++
  }

  return { scenarioId: "courseware", snapshotId, runsUpdated, samplesUpdated }
}

// CLI 入口（直接执行时运行）
async function main() {
  const { PrismaClient } = await import("@prisma/client")
  const prisma = new PrismaClient()
  try {
    const res = await migrateHistoricalMetrics(prisma)
    console.log("✅ 历史指标迁移完成：", res)
  } finally {
    await prisma.$disconnect()
  }
}

// CLI 入口检测：仅当本文件被直接执行（tsx scripts/migrateHistoricalMetrics.ts）时运行 main，
// 被 vitest/其它模块 import 时不触发（process.argv[1] 为调用方路径）。
const invokedDirectly =
  typeof process !== "undefined" && !!process.argv[1]?.includes("migrateHistoricalMetrics.ts")
if (invokedDirectly) {
  main().catch((e) => {
    console.error("❌ 迁移失败：", e)
    process.exit(1)
  })
}
