/**
 * 一次性历史指标迁移（Phase 3，对齐 09 §9.5.6 / §11.3 阶段B）。
 *
 * 把存量 Run/Sample 的遗留一等指标列（dr/cpr/avg_reward/...、s_format/...）回填到
 * metrics JSONB，并为每条 Run 关联 courseware 默认 RunConfigSnapshot。无前端 fallback：
 * 迁移完成后所有历史 Run 均具备完整场景化 metrics + 快照，前端可彻底动态渲染。
 *
 * 幂等：仅处理 metrics 为空的行 / run_config_snapshot_id 为空的行，可安全重跑。
 * 兼容：即使遗留列已被后续 drop 迁移删除（P5-8 阶段C），本脚本仍可正常执行
 * （跳过去列回填，仅补齐 snapshot 与 scenario/package 关联）。
 *
 * 用法：npx tsx scripts/migrateHistoricalMetrics.ts   （读 PLATFORM_DATABASE_URL）
 */

import { createHash } from "crypto"
import { type PrismaClient } from "@prisma/client"
import {
  COURSEWARE_DEFAULT_METRIC_DEFS,
  COURSEWARE_DEFAULT_AGGREGATION_POLICY,
} from "../src/config/coursewareDefaults"

// 单一源（src/config/coursewareDefaults.ts），本脚本与 import 脚本共用
const COURSEWARE_METRIC_DEFINITIONS = COURSEWARE_DEFAULT_METRIC_DEFS
const COURSEWARE_AGGREGATION_POLICY = COURSEWARE_DEFAULT_AGGREGATION_POLICY
const COURSEWARE_SCENARIO_ID = "courseware"

export interface MigrationResult {
  scenarioId: string
  snapshotId: string
  runsUpdated: number
  samplesUpdated: number
  runsSnapshotted: number
}

/** 检测某表是否存在指定列（用于兼容 drop 迁移后的库）。 */
async function hasColumn(prisma: PrismaClient, table: string, column: string): Promise<boolean> {
  const rows = await prisma.$queryRawUnsafe<{ exists: boolean }[]>(
    `SELECT EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = ${escapeLiteral(table)} AND column_name = ${escapeLiteral(column)}
     ) AS exists`,
  )
  return rows[0]?.exists ?? false
}

function escapeLiteral(value: string): string {
  return "'" + value.replace(/'/g, "''") + "'"
}

/** 执行一次性历史指标迁移。幂等（仅处理缺失数据的行）。 */
export async function migrateHistoricalMetrics(prisma: PrismaClient): Promise<MigrationResult> {
  // 1. 确保 courseware 场景存在（不覆盖已有 defaultMetricDefinitions，由 importAssetsToDb 负责写入权威定义）
  await prisma.scenario.upsert({
    where: { id: COURSEWARE_SCENARIO_ID },
    update: {},
    create: {
      id: COURSEWARE_SCENARIO_ID,
      name: "课件质量评估",
      description: "课件生成场景默认包",
    },
  })

  // 2. 找到/创建 courseware 默认 RunConfigSnapshot（按 content_hash 去重）
  const content = {
    scenario_id: COURSEWARE_SCENARIO_ID,
    package: { id: COURSEWARE_SCENARIO_ID, version: "1.0.0" },
    aggregation_policy: COURSEWARE_AGGREGATION_POLICY,
    metric_definitions: COURSEWARE_METRIC_DEFINITIONS,
  }
  const contentHash =
    "sha256:" + createHash("sha256").update(JSON.stringify(content)).digest("hex")
  const snapshot = await prisma.runConfigSnapshot.findFirst({ where: { contentHash } })
  const snapshotId = snapshot
    ? snapshot.id
    : (
        await prisma.runConfigSnapshot.create({
          data: {
            scenarioId: COURSEWARE_SCENARIO_ID,
            packageId: COURSEWARE_SCENARIO_ID,
            packageVersion: "1.0.0",
            content: content as unknown as never,
            contentHash,
          },
          select: { id: true },
        })
      ).id

  // 3. 回填 Run.metrics（仅当遗留列仍存在时；drop 迁移后由其他方式保证 metrics 已存在）
  let runsUpdated = 0
  if (await hasColumn(prisma, "runs", "dr")) {
    const runsResult = await prisma.$executeRawUnsafe(
      `UPDATE runs
       SET metrics = jsonb_build_object(
         'courseware:document_rate', dr,
         'courseware:constraint_pass_rate', cpr,
         'courseware:reward', avg_reward,
         'courseware:soft', avg_soft,
         'courseware:pref', avg_pref,
         'courseware:conditional_reward', cond_r,
         'avg_time_ms', avg_time_ms
       )
       WHERE metrics IS NULL
         AND dr IS NOT NULL
         AND cpr IS NOT NULL
         AND avg_reward IS NOT NULL`,
    )
    runsUpdated = Number(runsResult)
  }

  // 4. 回填 Sample.metrics（仅当遗留列仍存在时）
  let samplesUpdated = 0
  if (await hasColumn(prisma, "samples", "s_format")) {
    const samplesResult = await prisma.$executeRawUnsafe(
      `UPDATE samples
       SET metrics = jsonb_build_object(
         'courseware:format', s_format,
         'courseware:commonsense', s_common,
         'courseware:soft', s_soft,
         'courseware:pref', s_pref,
         'courseware:reward', reward
       )
       WHERE metrics IS NULL
         AND s_format IS NOT NULL
         AND s_common IS NOT NULL
         AND s_soft IS NOT NULL
         AND s_pref IS NOT NULL`,
    )
    samplesUpdated = Number(samplesResult)
  }

  // 5. 为所有历史 Run 补齐 scenario/package 关联与 snapshot（幂等）
  const snapshottedResult = await prisma.$executeRawUnsafe(
    `UPDATE runs
     SET scenario_id = ${escapeLiteral(COURSEWARE_SCENARIO_ID)},
         package_id = ${escapeLiteral(COURSEWARE_SCENARIO_ID)},
         package_version = '1.0.0',
         run_config_snapshot_id = ${escapeLiteral(snapshotId)}
     WHERE run_config_snapshot_id IS NULL`,
  )
  const runsSnapshotted = Number(snapshottedResult)

  return {
    scenarioId: COURSEWARE_SCENARIO_ID,
    snapshotId,
    runsUpdated,
    samplesUpdated,
    runsSnapshotted,
  }
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
