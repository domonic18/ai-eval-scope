/**
 * 场景默认指标定义 + 聚合策略 GET 测试（docs/plan/08 Web 纯可视化：配置只读）。
 * 写入通道只剩登记脚本（importAssetsToDb，通道 A）——测试用同一 repo 方法播种，
 * 路由层不再提供 POST；并守护写端点已移除（404）。
 */

import { describe, it, expect, afterEach } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { registerUser } from "./helpers"
import { getPrisma } from "../src/infra/prisma"
import { ScenarioRepository } from "../src/repositories/scenario.repository"

const prisma = getPrisma()
const SCENARIO_ID = `test-defaults-${Date.now()}`
const USER_EMAIL: string[] = []
const ORG_SLUGS: string[] = []

afterEach(async () => {
  await prisma.defaultsAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
  await prisma.scenario.deleteMany({ where: { id: SCENARIO_ID } }).catch(() => {})
  for (const slug of ORG_SLUGS) {
    await prisma.organization.deleteMany({ where: { slug } }).catch(() => {})
  }
  for (const email of USER_EMAIL) {
    await prisma.user.deleteMany({ where: { email } }).catch(() => {})
  }
  ORG_SLUGS.length = 0
  USER_EMAIL.length = 0
})

const METRICS_V1 = [
  { id: "DR", name: "文档评分", expression: "score", threshold: 0.6, unit: "%" },
]
const POLICY_V1 = {
  id: "default",
  stage_weights: [{ stage_id: "format", weight: 1, is_gate: true }],
}

/** 通道 A 播种：登记脚本同款 repo 方法（publishDefaultsAsset）。 */
async function seedVersion(version: string, metrics: unknown[], policy: unknown) {
  await new ScenarioRepository().publishDefaultsAsset(SCENARIO_ID, {
    version,
    labels: ["latest"],
    content: { metric_definitions: metrics, aggregation_policy: policy },
    createdBy: "importAssetsToDb",
  })
}

describe("GET /api/v1/scenarios/:id/defaults", () => {
  it("returns latest published version content (public, no auth)", async () => {
    const app = createApp()
    await seedVersion("1.0.0", METRICS_V1, POLICY_V1)
    await seedVersion("1.1.0", [{ id: "DR", threshold: 0.7 }], POLICY_V1)

    const res = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/defaults`)
    expect(res.status).toBe(200)
    expect(res.body.metric_definitions).toEqual([{ id: "DR", threshold: 0.7 }])
    expect(res.body.aggregation_policy).toEqual(POLICY_V1)
  })

  it("resolves by explicit ?version=", async () => {
    const app = createApp()
    await seedVersion("1.0.0", METRICS_V1, POLICY_V1)
    await seedVersion("1.1.0", [{ id: "DR", threshold: 0.7 }], POLICY_V1)

    const res = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/defaults?version=1.0.0`)
    expect(res.status).toBe(200)
    expect(res.body.metric_definitions).toEqual(METRICS_V1)
  })

  it("returns empty defs for scenario without defaults", async () => {
    const app = createApp()
    await prisma.scenario.create({ data: { id: SCENARIO_ID, name: SCENARIO_ID } })
    const res = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/defaults`)
    expect(res.status).toBe(200)
    expect(res.body.metric_definitions).toEqual([])
    expect(res.body.aggregation_policy).toBeNull()
  })

  it("returns 404 for unknown scenario", async () => {
    const app = createApp()
    const res = await request(app).get(`/api/v1/scenarios/nope/defaults`)
    expect(res.status).toBe(404)
  })
})

describe("GET /api/v1/scenarios/:id/defaults/versions", () => {
  it("lists version history desc with labels and contentHash", async () => {
    const app = createApp()
    await seedVersion("1.0.0", METRICS_V1, POLICY_V1)
    await seedVersion("1.1.0", METRICS_V1, POLICY_V1)

    const res = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/defaults/versions`)
    expect(res.status).toBe(200)
    expect(res.body.versions.map((v: { version: string }) => v.version)).toEqual(["1.1.0", "1.0.0"])
    expect(res.body.versions[0].labels).toContain("latest")
    expect(typeof res.body.versions[0].contentHash).toBe("string")
  })
})

describe("config write endpoints removed (docs/plan/08 纯可视化)", () => {
  it("POST /:id/defaults → 404", async () => {
    const app = createApp()
    const u = await registerUser(app, "def-gone")
    USER_EMAIL.push(u.email)
    ORG_SLUGS.push(u.org.slug)
    const res = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/defaults`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send({ version: "1.0.0", metric_definitions: METRICS_V1 })
    expect(res.status).toBe(404)
  })

  it("POST / (create scenario) → 404", async () => {
    const app = createApp()
    const res = await request(app)
      .post("/api/v1/scenarios")
      .send({ id: SCENARIO_ID, name: SCENARIO_ID })
    expect(res.status).toBe(404)
  })
})
