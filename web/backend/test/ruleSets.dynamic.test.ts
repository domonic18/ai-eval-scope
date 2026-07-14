/**
 * Phase 3 动态规则集目录测试（/api/v1/rule-sets，对齐 12 §6.4）。
 * DB RuleSetAsset 与静态 catalog 合并；第三方据此发现场景包（package_id 语义）。
 */

import { describe, it, expect, afterEach } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const SCENARIO_ID = `test-rs-${Date.now()}`

afterEach(async () => {
  await prisma.ruleSetAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
  await prisma.scenario.deleteMany({ where: { id: SCENARIO_ID } }).catch(() => {})
})

describe("GET /api/v1/rule-sets (dynamic)", () => {
  it("merges DB package assets with static catalog capabilities", async () => {
    const app = createApp()
    await prisma.scenario.create({ data: { id: SCENARIO_ID, name: "T" } })
    await prisma.ruleSetAsset.create({
      data: {
        scenarioId: SCENARIO_ID,
        assetId: "custom-pkg",
        version: "2.0.0",
        labels: ["production"],
        contentHash: "h",
        content: { name: "自定义包", description: "动态注入" },
        createdBy: "test",
      },
    })

    const res = await request(app).get("/api/v1/rule-sets")
    expect(res.status).toBe(200)
    const sets = res.body.rule_sets as Array<Record<string, unknown>>
    const custom = sets.find((s) => s.id === "custom-pkg")
    expect(custom).toBeTruthy()
    expect(custom!.name).toBe("自定义包")
    expect(custom!.scenario_id).toBe(SCENARIO_ID)
    expect(custom!.version).toBe("2.0.0")
    // 静态 catalog 中既有的（如 coursework-quality）仍出现
    expect(sets.some((s) => s.id === "coursework-quality" || s.id === "coursework-gate")).toBe(true)
  })
})
