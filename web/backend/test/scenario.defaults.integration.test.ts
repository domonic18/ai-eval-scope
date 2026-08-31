/**
 * 场景默认指标定义 + 聚合策略发布测试（POST /api/v1/scenarios/:id/defaults，platform admin）。
 * 发布为版本化动作（version 必填，201 + { asset }），GET 返回最新已发布版本内容。
 * 镜像 scenario.publish.integration.test.ts 的 registerUser + 提升 admin 模式。
 */

import { describe, it, expect, afterEach } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { registerUser } from "./helpers"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const SCENARIO_ID = `test-defaults-${Date.now()}`
const USER_EMAIL: string[] = []
const ORG_SLUGS: string[] = []

afterEach(async () => {
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

/** 注册用户并提升为平台 admin。 */
async function makeAdmin(app: ReturnType<typeof createApp>, prefix: string) {
  const u = await registerUser(app, prefix)
  USER_EMAIL.push(u.email)
  ORG_SLUGS.push(u.org.slug)
  await prisma.user.update({ where: { email: u.email }, data: { role: "admin" } })
  return u
}

describe("POST /api/v1/scenarios/:id/defaults", () => {
  it("rejects without admin (403)", async () => {
    const app = createApp()
    const u = await registerUser(app, "def-noadmin")
    USER_EMAIL.push(u.email)
    ORG_SLUGS.push(u.org.slug)
    const res = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/defaults`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send({ version: "1.0.0", metric_definitions: [{ id: "DR" }] })
    expect(res.status).toBe(403)
  })

  it("rejects empty body (400)", async () => {
    const app = createApp()
    const u = await makeAdmin(app, "def-empty")
    await prisma.scenario.create({ data: { id: SCENARIO_ID, name: SCENARIO_ID } })
    const res = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/defaults`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send({})
    expect(res.status).toBe(400)
  })

  it("rejects bad metric_definitions type (400)", async () => {
    const app = createApp()
    const u = await makeAdmin(app, "def-bad")
    await prisma.scenario.create({ data: { id: SCENARIO_ID, name: SCENARIO_ID } })
    const res = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/defaults`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send({ version: "1.0.0", metric_definitions: "not-an-array" })
    expect(res.status).toBe(400)
  })

  it("publishes metric_definitions & aggregation_policy as admin, reflected by GET", async () => {
    const app = createApp()
    const u = await makeAdmin(app, "def-ok")
    await prisma.scenario.create({ data: { id: SCENARIO_ID, name: SCENARIO_ID } })

    const metrics = [
      { id: "DR", name: "文档评分", expression: "score", threshold: 0.6, unit: "%" },
    ]
    const policy = {
      id: "default",
      stage_weights: [{ stage_id: "format", weight: 1, is_gate: true }],
    }

    const res = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/defaults`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send({ version: "1.0.0", metric_definitions: metrics, aggregation_policy: policy })
    expect(res.status).toBe(201)
    // publishDefaultsAsset 返回 { assetId: "default", version }（assetId 固定 "default"）
    expect(res.body.asset?.assetId).toBe("default")
    expect(res.body.asset?.version).toBe("1.0.0")

    // GET 应反映新值（最新已发布版本内容）
    const got = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/defaults`)
    expect(got.status).toBe(200)
    expect(got.body.metric_definitions).toEqual(metrics)
    expect(got.body.aggregation_policy).toEqual(policy)
  })
})
