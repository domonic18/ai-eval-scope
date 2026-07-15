/**
 * Phase 3 动态 catalog 路由测试（/api/v1/scenarios/:id/catalog）。
 * 直接 seed scenarios / *_assets 表，校验 catalog 聚合与 latest 解析。
 */

import { describe, it, expect, afterEach } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const SCENARIO_ID = `test-catalog-${Date.now()}`

async function seed() {
  await prisma.scenario.create({
    data: {
      id: SCENARIO_ID,
      name: "测试场景",
      description: "Phase 3 catalog 测试",
    },
  })
  // 规则集：两个版本，1.1.0 带 production 标签 → catalog 应选它
  await prisma.ruleSetAsset.create({
    data: {
      scenarioId: SCENARIO_ID,
      assetId: "quality",
      version: "1.0.0",
      labels: ["latest"],
      contentHash: "h1",
      content: { name: "质量评估", description: "v1" },
      createdBy: "test",
    },
  })
  await prisma.ruleSetAsset.create({
    data: {
      scenarioId: SCENARIO_ID,
      assetId: "quality",
      version: "1.1.0",
      labels: ["production"],
      contentHash: "h2",
      content: { name: "质量评估", description: "v1.1" },
      createdBy: "test",
    },
  })
  await prisma.promptTemplateAsset.create({
    data: {
      scenarioId: SCENARIO_ID,
      assetId: "pedagogical_logic",
      namespace: SCENARIO_ID,
      version: "1.0.0",
      labels: ["production"],
      contentHash: "hp",
      content: { name: "教学逻辑" },
      createdBy: "test",
    },
  })
  await prisma.datasetAsset.create({
    data: {
      scenarioId: SCENARIO_ID,
      assetId: "math_reference",
      role: "reference",
      version: "1.0.0",
      labels: ["latest"],
      backendType: "yaml_file",
      backendConfig: {},
      contentHash: "hd",
      content: { name: "数学参考" },
      createdBy: "test",
    },
  })
}

afterEach(async () => {
  await prisma.ruleSetAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } })
  await prisma.promptTemplateAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } })
  await prisma.datasetAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } })
  await prisma.scenario.deleteMany({ where: { id: SCENARIO_ID } })
})

describe("GET /api/v1/scenarios", () => {
  it("lists scenarios including seeded one", async () => {
    const app = createApp()
    await seed()
    const res = await request(app).get("/api/v1/scenarios")
    expect(res.status).toBe(200)
    const ids = res.body.scenarios.map((s: { id: string }) => s.id)
    expect(ids).toContain(SCENARIO_ID)
  })
})

describe("GET /api/v1/scenarios/:id/catalog", () => {
  it("returns rule_sets/prompts/datasets and picks production version", async () => {
    const app = createApp()
    await seed()
    const res = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/catalog`)
    expect(res.status).toBe(200)
    expect(res.body.scenario.id).toBe(SCENARIO_ID)

    const ruleSets = res.body.rule_sets as Array<{ asset_id: string; version: string }>
    expect(ruleSets).toHaveLength(1)
    expect(ruleSets[0].asset_id).toBe("quality")
    expect(ruleSets[0].version).toBe("1.1.0") // production 标签优先于 1.0.0

    expect((res.body.prompts as unknown[]).length).toBe(1)
    const datasets = res.body.datasets as Array<{ role: string; backend_type: string }>
    expect(datasets).toHaveLength(1)
    expect(datasets[0].role).toBe("reference")
    expect(datasets[0].backend_type).toBe("yaml_file")
  })

  it("404 for unknown scenario", async () => {
    const app = createApp()
    const res = await request(app).get("/api/v1/scenarios/no-such-scenario/catalog")
    expect(res.status).toBe(404)
  })
})
