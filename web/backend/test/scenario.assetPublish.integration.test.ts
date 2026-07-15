/**
 * Phase 4 asset 级发布 + 版本/标签路由测试。
 * POST /scenarios/:id/{rule-sets,prompts,datasets}、versions 列表、标签晋升。
 */

import { describe, it, expect, afterEach } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { registerUser } from "./helpers"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const SCENARIO_ID = `test-asset-${Date.now()}`
const USER_EMAIL: string[] = []
const ORG_SLUGS: string[] = []

afterEach(async () => {
  await prisma.ruleSetAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
  await prisma.promptTemplateAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
  await prisma.datasetAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
  await prisma.scenario.deleteMany({ where: { id: SCENARIO_ID } }).catch(() => {})
  for (const slug of ORG_SLUGS) await prisma.organization.deleteMany({ where: { slug } }).catch(() => {})
  for (const email of USER_EMAIL) await prisma.user.deleteMany({ where: { email } }).catch(() => {})
  ORG_SLUGS.length = 0
  USER_EMAIL.length = 0
})

async function adminToken(app: ReturnType<typeof createApp>, tag: string) {
  const u = await registerUser(app, tag)
  USER_EMAIL.push(u.email)
  ORG_SLUGS.push(u.org.slug)
  await prisma.user.update({ where: { email: u.email }, data: { role: "admin" } })
  return u.accessToken
}

describe("Phase 4 asset publish", () => {
  it("publishes rule-set + dataset assets (admin, idempotent)", async () => {
    const app = createApp()
    const tok = await adminToken(app, "asset-rs")

    const rs = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/rule-sets`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "quality", version: "1.0.0", labels: ["latest"], content: { name: "Q", rules: [] } })
    expect(rs.status).toBe(201)

    const ds = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/datasets`)
      .set("Authorization", `Bearer ${tok}`)
      .send({
        asset_id: "math_ref",
        role: "reference",
        version: "1.0.0",
        backend_type: "yaml_file",
        backend_config: { file: "math.yaml" },
        content: { subject: "math" },
      })
    expect(ds.status).toBe(201)

    // catalog 反映新资产
    const cat = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/catalog`)
    expect(cat.body.rule_sets.find((r: { asset_id: string }) => r.asset_id === "quality")).toBeTruthy()
    expect(cat.body.datasets.find((d: { asset_id: string }) => d.asset_id === "math_ref")?.role).toBe("reference")

    // 400 缺字段
    const bad = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/rule-sets`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ labels: [] })
    expect(bad.status).toBe(400)

    // 403 非 admin
    const nonAdmin = await registerUser(app, "asset-no")
    USER_EMAIL.push(nonAdmin.email)
    ORG_SLUGS.push(nonAdmin.org.slug)
    const forbidden = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/rule-sets`)
      .set("Authorization", `Bearer ${nonAdmin.accessToken}`)
      .send({ asset_id: "x", version: "1.0.0" })
    expect(forbidden.status).toBe(403)
  })

  it("lists versions + promotes labels", async () => {
    const app = createApp()
    const tok = await adminToken(app, "asset-ver")
    // 发两个版本
    await request(app).post(`/api/v1/scenarios/${SCENARIO_ID}/rule-sets`).set("Authorization", `Bearer ${tok}`).send({
      asset_id: "q",
      version: "1.0.0",
      labels: ["latest"],
      content: { v: 1 },
    })
    await request(app).post(`/api/v1/scenarios/${SCENARIO_ID}/rule-sets`).set("Authorization", `Bearer ${tok}`).send({
      asset_id: "q",
      version: "1.1.0",
      labels: [],
      content: { v: 2 },
    })

    const versions = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/rule-sets/q/versions`)
    expect(versions.status).toBe(200)
    expect(versions.body.versions.length).toBe(2)

    // 标签晋升：把 1.1.0 标 production
    const promote = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/rule-sets/q/versions/1.1.0/labels`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ labels: ["production"] })
    expect(promote.status).toBe(200)

    const row = await prisma.ruleSetAsset.findUnique({
      where: { scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: "q", version: "1.1.0" } },
    })
    expect(row?.labels).toEqual(["production"])
  })
})
