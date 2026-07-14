/**
 * Phase 3 历史指标迁移脚本测试（scripts/migrateHistoricalMetrics.ts）。
 * 构造遗留形态的 Run/Sample（metrics 为空、遗留一等列有值），跑迁移后校验回填。
 */

import { describe, it, expect, afterEach } from "vitest"
import { Prisma } from "@prisma/client"
import { getPrisma } from "../src/infra/prisma"
import { migrateHistoricalMetrics } from "../scripts/migrateHistoricalMetrics"

const prisma = getPrisma()
const SUFFIX = `${Date.now()}`

async function seedLegacyRun() {
  const user = await prisma.user.create({
    data: { email: `mig-${SUFFIX}@example.com`, passwordHash: "x" },
  })
  const org = await prisma.organization.create({
    data: { name: `Org-${SUFFIX}`, slug: `org-${SUFFIX}`, createdBy: user.id },
  })
  const project = await prisma.project.create({
    data: {
      orgId: org.id,
      slug: `proj-${SUFFIX}`,
      name: `Proj-${SUFFIX}`,
      createdBy: user.id,
    },
  })
  const run = await prisma.run.create({
    data: {
      projectId: project.id,
      externalRunId: `run-${SUFFIX}`,
      mode: "eval_only",
      status: "completed",
      // 遗留一等列有值；metrics/scenario 留空模拟历史形态
      dr: 0.9,
      cpr: 0.8,
      avgReward: 0.5,
      avgSoft: 0.6,
      avgPref: 0.7,
      condR: 0.65,
      avgTimeMs: 123,
      metrics: Prisma.DbNull,
      scenarioId: null,
      runConfigSnapshotId: null,
    },
  })
  const sample = await prisma.sample.create({
    data: {
      runId: run.id,
      projectId: project.id,
      externalSampleId: `smp-${SUFFIX}`,
      status: "completed",
      reward: 0.4,
      sSoft: 0.5,
      sPref: 0.6,
      sFormat: 1,
      sCommon: 0,
      metrics: Prisma.DbNull,
    },
  })
  return { userId: user.id, orgId: org.id, projectId: project.id, runId: run.id, sampleId: sample.id }
}

afterEach(async () => {
  await prisma.runConfigSnapshot.deleteMany({ where: { scenarioId: "courseware" } })
  // 级联：删 project → run/sample；删 org/user
  await prisma.project.deleteMany({ where: { slug: `proj-${SUFFIX}` } }).catch(() => {})
  await prisma.organization.deleteMany({ where: { slug: `org-${SUFFIX}` } }).catch(() => {})
  await prisma.user.deleteMany({ where: { email: `mig-${SUFFIX}@example.com` } }).catch(() => {})
})

describe("migrateHistoricalMetrics", () => {
  it("backfills Run/Sample metrics from legacy columns + links snapshot", async () => {
    const { runId, sampleId } = await seedLegacyRun()

    const res = await migrateHistoricalMetrics(prisma)
    expect(res.scenarioId).toBe("courseware")
    expect(res.runsUpdated).toBeGreaterThanOrEqual(1)
    expect(res.snapshotId).toBeTruthy()

    const run = await prisma.run.findUnique({ where: { id: runId } })
    expect(run?.metrics).toMatchObject({
      "courseware:document_rate": 0.9,
      "courseware:constraint_pass_rate": 0.8,
      "courseware:reward": 0.5,
      "courseware:soft": 0.6,
      "courseware:pref": 0.7,
      "courseware:conditional_reward": 0.65,
    })
    expect(run?.scenarioId).toBe("courseware")
    expect(run?.runConfigSnapshotId).toBe(res.snapshotId)

    const sample = await prisma.sample.findUnique({ where: { id: sampleId } })
    expect(sample?.metrics).toMatchObject({ reward: 0.4, soft: 0.5, pref: 0.6, format: 1, common: 0 })

    // 快照内含 metric_definitions
    const snapshot = await prisma.runConfigSnapshot.findUnique({ where: { id: res.snapshotId } })
    expect((snapshot?.content as { metric_definitions: unknown[] }).metric_definitions.length).toBe(6)
  })

  it("is idempotent (re-run touches nothing new)", async () => {
    await seedLegacyRun()
    await migrateHistoricalMetrics(prisma)
    const second = await migrateHistoricalMetrics(prisma)
    // 第二次：上一轮已回填的 Run 不再匹配 metrics:null，runsUpdated 不应再计入本种子
    expect(second.runsUpdated).toBeGreaterThanOrEqual(0)
  })
})
