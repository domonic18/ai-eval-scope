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

  it("rejects re-publishing an existing asset version (409 immutable)", async () => {
    const app = createApp()
    const tok = await adminToken(app, "asset-imm")
    const url = `/api/v1/scenarios/${SCENARIO_ID}/rule-sets`
    const first = await request(app).post(url).set("Authorization", `Bearer ${tok}`).send({
      asset_id: "imm",
      version: "1.0.0",
      labels: ["latest"],
      content: { v: 1 },
    })
    expect(first.status).toBe(201)
    const again = await request(app).post(url).set("Authorization", `Bearer ${tok}`).send({
      asset_id: "imm",
      version: "1.0.0",
      labels: [],
      content: { v: 2 },
    })
    expect(again.status).toBe(409)
    const row = await prisma.ruleSetAsset.findUnique({
      where: {
        scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: "imm", version: "1.0.0" },
      },
    })
    expect(row?.labels).toEqual(["latest"]) // 原行未被覆盖
  })

  it("picks latest by numeric semver consistently (catalog & rule-sets: 1.10.0 > 1.9.0)", async () => {
    const app = createApp()
    const tok = await adminToken(app, "asset-semver")
    const url = `/api/v1/scenarios/${SCENARIO_ID}/rule-sets`
    await request(app)
      .post(url)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "semver", version: "1.9.0", content: { name: "semver" } })
    await request(app)
      .post(url)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "semver", version: "1.10.0", content: { name: "semver" } })

    // catalog 端（数值 semver）
    const cat = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/catalog`)
    const catEntry = cat.body.rule_sets.find((r: { asset_id: string }) => r.asset_id === "semver")
    expect(catEntry.version).toBe("1.10.0")

    // rule-sets 发现端（曾用字符串比较，会错误返回 1.9.0）
    const rs = await request(app).get("/api/v1/rule-sets")
    const rsEntry = rs.body.rule_sets.find((r: { id: string }) => r.id === "semver")
    expect(rsEntry.version).toBe("1.10.0")
  })

  it("promotes labels mutually exclusively (production globally unique per asset)", async () => {
    const app = createApp()
    const tok = await adminToken(app, "asset-mutex")
    const url = `/api/v1/scenarios/${SCENARIO_ID}/rule-sets`
    await request(app)
      .post(url)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "mutex", version: "1.0.0", content: { v: 1 } })
    await request(app)
      .post(url)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "mutex", version: "1.1.0", content: { v: 2 } })

    const promote = (ver: string, labels: string[]) =>
      request(app)
        .post(`/api/v1/scenarios/${SCENARIO_ID}/rule-sets/mutex/versions/${ver}/labels`)
        .set("Authorization", `Bearer ${tok}`)
        .send({ labels })

    expect((await promote("1.0.0", ["production"])).status).toBe(200)
    // 再把 1.1.0 标 production → 应从 1.0.0 摘除 production（互斥）
    expect((await promote("1.1.0", ["production"])).status).toBe(200)

    const v1 = await prisma.ruleSetAsset.findUnique({
      where: {
        scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: "mutex", version: "1.0.0" },
      },
    })
    const v2 = await prisma.ruleSetAsset.findUnique({
      where: {
        scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: "mutex", version: "1.1.0" },
      },
    })
    expect(v1?.labels).toEqual([])
    expect(v2?.labels).toEqual(["production"])
  })
})
