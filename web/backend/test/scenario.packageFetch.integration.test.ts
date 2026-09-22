/**
 * S2-A 场景包内容拉取（GET /api/v1/scenarios/:id/packages/:assetId，公开读）。
 * 验证 executor/evaluator 运行时按 version / label / latest 解析包内容。
 * 播种走登记通道（repo.publishPackage，importAssetsToDb 同款；docs/plan/08 纯可视化后
 * 路由层不再提供 POST）。
 */

import { describe, it, expect, afterEach } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { getPrisma } from "../src/infra/prisma"
import { ScenarioRepository } from "../src/repositories/scenario.repository"

const prisma = getPrisma()
const SCENARIO_ID = `test-fetch-${Date.now()}`

afterEach(async () => {
  await prisma.scenarioPackage.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
  await prisma.scenario.deleteMany({ where: { id: SCENARIO_ID } }).catch(() => {})
})

const repo = new ScenarioRepository()
const FILES = {
  manifest: { id: "quality", version: "1.0.0", scenario: "courseware" },
  files: {
    "rules/quality.yaml": "rules: []",
    "prompts/info_accuracy.yaml": "template_id: info_accuracy",
  },
}
const seed = (assetId: string, version: string, labels: string[]) =>
  repo.publishPackage(SCENARIO_ID, { assetId, version, labels, content: FILES, createdBy: "importAssetsToDb" })

describe("GET /api/v1/scenarios/:id/packages/:assetId (S2-A)", () => {
  it("resolves by label=production and returns {manifest, files} content (public, no auth)", async () => {
    const app = createApp()
    await seed("quality", "1.0.0", ["production"])

    const res = await request(app).get(
      `/api/v1/scenarios/${SCENARIO_ID}/packages/quality?label=production`,
    )
    expect(res.status).toBe(200)
    expect(res.body.package.version).toBe("1.0.0")
    expect(res.body.package.labels).toContain("production")
    expect(res.body.package.content.files["rules/quality.yaml"]).toBe("rules: []")
  })

  it("resolves by explicit version", async () => {
    const app = createApp()
    await seed("quality", "2.0.0", ["latest"])

    const res = await request(app).get(
      `/api/v1/scenarios/${SCENARIO_ID}/packages/quality?version=2.0.0`,
    )
    expect(res.status).toBe(200)
    expect(res.body.package.version).toBe("2.0.0")
  })

  it("defaults to latest (rank+semver) when no version/label", async () => {
    const app = createApp()
    await seed("quality", "1.9.0", [])
    await seed("quality", "1.10.0", [])

    const res = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/packages/quality`)
    expect(res.status).toBe(200)
    expect(res.body.package.version).toBe("1.10.0")
  })

  it("returns 404 for unknown package", async () => {
    const app = createApp()
    const res = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/packages/nope`)
    expect(res.status).toBe(404)
  })
})
