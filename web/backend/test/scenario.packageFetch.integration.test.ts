/**
 * S2-A 场景包内容拉取（GET /api/v1/scenarios/:id/packages/:assetId，公开读）。
 * 验证 executor/evaluator 运行时按 version / label / latest 解析包内容。
 */

import { describe, it, expect, afterEach } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { registerUser } from "./helpers"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const SCENARIO_ID = `test-fetch-${Date.now()}`
const USER_EMAIL: string[] = []
const ORG_SLUGS: string[] = []

afterEach(async () => {
  await prisma.scenarioPackage.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
  await prisma.scenario.deleteMany({ where: { id: SCENARIO_ID } }).catch(() => {})
  for (const slug of ORG_SLUGS) await prisma.organization.deleteMany({ where: { slug } }).catch(() => {})
  for (const email of USER_EMAIL) await prisma.user.deleteMany({ where: { email } }).catch(() => {})
  ORG_SLUGS.length = 0
  USER_EMAIL.length = 0
})

async function adminToken(app: ReturnType<typeof createApp>, tag: string): Promise<string> {
  const u = await registerUser(app, tag)
  USER_EMAIL.push(u.email)
  ORG_SLUGS.push(u.org.slug)
  await prisma.user.update({ where: { email: u.email }, data: { role: "admin" } })
  return u.accessToken
}

const FILES = {
  manifest: { id: "quality", version: "1.0.0", scenario: "courseware" },
  files: {
    "rules/quality.yaml": "rules: []",
    "prompts/info_accuracy.yaml": "template_id: info_accuracy",
  },
}

describe("GET /api/v1/scenarios/:id/packages/:assetId (S2-A)", () => {
  it("resolves by label=production and returns {manifest, files} content (public, no auth)", async () => {
    const app = createApp()
    const tok = await adminToken(app, "fetch-label")
    await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/packages`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "quality", version: "1.0.0", labels: ["production"], content: FILES })

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
    const tok = await adminToken(app, "fetch-ver")
    await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/packages`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "quality", version: "2.0.0", labels: ["latest"], content: FILES })

    const res = await request(app).get(
      `/api/v1/scenarios/${SCENARIO_ID}/packages/quality?version=2.0.0`,
    )
    expect(res.status).toBe(200)
    expect(res.body.package.version).toBe("2.0.0")
  })

  it("defaults to latest (rank+semver) when no version/label", async () => {
    const app = createApp()
    const tok = await adminToken(app, "fetch-latest")
    const post = (ver: string, labels: string[]) =>
      request(app)
        .post(`/api/v1/scenarios/${SCENARIO_ID}/packages`)
        .set("Authorization", `Bearer ${tok}`)
        .send({ asset_id: "quality", version: ver, labels, content: FILES })
    await post("1.9.0", [])
    await post("1.10.0", [])

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
