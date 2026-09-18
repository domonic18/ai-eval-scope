/**
 * 场景样本视图呈现配置集成测试（docs/arch/09 §9.7）：
 * platformAdminGuard（403/200）+ 服务端校验（词表/非空/去重/labels）+ 配置回读 + sampleDetail 带出。
 * 直接经 prisma 建真实用户/场景，supertest 打真实路由 + 真实 DB（同 admin.integration.test.ts 范式）。
 */
import request from "supertest"
import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { createApp } from "../src/server"
import { getPrisma } from "../src/infra/prisma"
import { hashPassword, issueAccessTokenResult } from "../src/infra/crypto"

const app = createApp()
const prisma = getPrisma()

const tag = Math.random().toString(36).slice(2, 8)
const adminEmail = `svadm_${tag}@example.com`
const userEmail = `svusr_${tag}@example.com`
const scenA = `sv_scn_a_${tag}`
const scenB = `sv_scn_b_${tag}`
let adminToken = ""
let userToken = ""
let adminId = ""
let userId = ""
let sampleDbId = ""
let projectId = ""
let orgId = ""

const auth = (tok: string) => ({ Authorization: `Bearer ${tok}` })

beforeAll(async () => {
  const admin = await prisma.user.create({
    data: { email: adminEmail, passwordHash: await hashPassword("password123"), role: "admin" },
  })
  const user = await prisma.user.create({
    data: { email: userEmail, passwordHash: await hashPassword("password123"), role: "user" },
  })
  adminId = admin.id
  userId = user.id
  adminToken = issueAccessTokenResult({ userId: adminId, platformAdmin: true }).access_token
  userToken = issueAccessTokenResult({ userId, platformAdmin: false }).access_token

  await prisma.scenario.createMany({
    data: [
      { id: scenA, name: `场景A-${tag}` },
      { id: scenB, name: `场景B-${tag}` },
    ],
  })
})

afterAll(async () => {
  // scenario 级联删除其 sample_view；sample/project 需显式清理（外键无级联到 project）
  await prisma.scenario.deleteMany({ where: { id: { in: [scenA, scenB] } } })
  if (sampleDbId) await prisma.sample.deleteMany({ where: { id: sampleDbId } })
  if (projectId) await prisma.project.deleteMany({ where: { id: projectId } })
  if (orgId) await prisma.organization.deleteMany({ where: { id: orgId } })
  await prisma.user.deleteMany({ where: { id: { in: [adminId, userId] } } })
})

describe("场景样本视图配置 /api/v1/admin/scenarios/:id/sample-view", () => {
  it("普通用户 → 403 FORBIDDEN", async () => {
    const r = await request(app)
      .get(`/api/v1/admin/scenarios/${scenA}/sample-view`)
      .set(auth(userToken))
    expect(r.status).toBe(403)
  })

  it("未登录 → 401", async () => {
    const r = await request(app).get(`/api/v1/admin/scenarios/${scenA}/sample-view`)
    expect(r.status).toBe(401)
  })

  it("未配置场景 GET → sampleView null", async () => {
    const r = await request(app)
      .get(`/api/v1/admin/scenarios/${scenA}/sample-view`)
      .set(auth(adminToken))
    expect(r.status).toBe(200)
    expect(r.body.sampleView).toBeNull()
  })

  it.each([
    ["tabs 缺失", {}],
    ["tabs 空", { tabs: [] }],
    ["非法 tab", { tabs: ["doc", "evil"] }],
    ["tab 重复", { tabs: ["doc", "doc", "trace"] }],
    ["labels.doc 空串", { tabs: ["doc"], labels: { doc: "  " } }],
    ["body 非对象", ["doc"]],
  ])("PUT 校验拒绝：%s → 400", async (_label, body) => {
    const r = await request(app)
      .put(`/api/v1/admin/scenarios/${scenA}/sample-view`)
      .set(auth(adminToken))
      .send(body)
    expect(r.status).toBe(400)
    expect(r.body.code).toBe("SCHEMA_INVALID")
  })

  it("PUT 合法配置 → 200 回读一致；未知键剥除", async () => {
    const cfg = { tabs: ["doc", "transcript", "shot"], labels: { doc: "Agent 回答" }, evil: 1 }
    const put = await request(app)
      .put(`/api/v1/admin/scenarios/${scenA}/sample-view`)
      .set(auth(adminToken))
      .send(cfg)
    expect(put.status).toBe(200)
    expect(put.body.sampleView).toEqual({ tabs: ["doc", "transcript", "shot"], labels: { doc: "Agent 回答" } })

    const get = await request(app)
      .get(`/api/v1/admin/scenarios/${scenA}/sample-view`)
      .set(auth(adminToken))
    expect(get.status).toBe(200)
    expect(get.body.sampleView.tabs).toEqual(["doc", "transcript", "shot"])
  })

  it("场景不存在 → 404", async () => {
    const r = await request(app)
      .get("/api/v1/admin/scenarios/no_such_scn/sample-view")
      .set(auth(adminToken))
    expect(r.status).toBe(404)
  })

  it("sampleDetail 响应带出 run.scenario.sampleView（零额外请求）", async () => {
    // 造 org → project → run → sample（外键链），B 场景配置后经样本详情读出
    const org = await prisma.organization.create({
      data: { name: `sv-org-${tag}`, slug: `sv-org-${tag}`, createdBy: adminId },
    })
    orgId = org.id
    const proj = await prisma.project.create({
      data: { name: `sv-proj-${tag}`, slug: `sv-${tag}`, orgId: org.id, createdBy: adminId },
    })
    projectId = proj.id
    const run = await prisma.run.create({
      data: {
        projectId: proj.id,
        externalRunId: `sv_run_${tag}`,
        mode: "eval_only",
        scenarioId: scenB,
        metrics: {},
      },
    })
    const sample = await prisma.sample.create({
      data: {
        runId: run.id,
        projectId: proj.id,
        externalSampleId: `sv_s_${tag}`,
        status: "completed",
      },
    })
    sampleDbId = sample.id

    const put = await request(app)
      .put(`/api/v1/admin/scenarios/${scenB}/sample-view`)
      .set(auth(adminToken))
      .send({ tabs: ["doc", "trace"] })
    expect(put.status).toBe(200)

    const r = await request(app).get(`/api/v1/runs/${run.id}`).set(auth(adminToken))
    expect(r.status).toBe(200)
    const sid = r.body.run.samples[0].id
    const detail = await request(app).get(`/api/v1/runs/${run.id}/samples/${sid}`).set(auth(adminToken))
    expect(detail.status).toBe(200)
    expect(detail.body.sample.run.scenarioId).toBe(scenB)
    expect(detail.body.sample.run.scenario.sampleView).toEqual({ tabs: ["doc", "trace"] })
  })
})
