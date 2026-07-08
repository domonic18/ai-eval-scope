/**
 * 公开项目 + iframe 嵌入 集成测试（docs/arch/12 §3.5）：
 *  - 未公开：匿名 GET 运行/样本详情 → 401
 *  - PATCH isPublic=true（owner）后：匿名 GET → 200
 *  - PATCH isPublic=false 后：匿名 GET → 401
 *  - 非成员 PATCH isPublic → 404（不泄露存在性）
 *  - member 不能改 isPublic（仅 owner）→ 403
 *
 * 依赖本地 docker 栈（postgres；run/sample/constraint 摄取不需对象存储）。
 */
import request from "supertest"
import { describe, it, expect, beforeAll } from "vitest"
import { createApp } from "../src/server"
import { registerUser, createProject, issueKey, bearerPost } from "./helpers"

const app = createApp()

const extRun = `pubrun_${Date.now()}_${Math.floor(Math.random() * 1e6)}`
const extSample = `pubsamp_${Date.now()}`
let owner: Awaited<ReturnType<typeof registerUser>>
let member: Awaited<ReturnType<typeof registerUser>>
let stranger: Awaited<ReturnType<typeof registerUser>>
let projectId: string
let keyToken: string
let sampleDbId: string

function ingest(events: object[]) {
  return bearerPost(app, {
    url: "/api/public/ingest",
    token: keyToken,
    bodyObj: { schema_version: "1.0", events },
  })
}

beforeAll(async () => {
  owner = await registerUser(app, "owner")
  member = await registerUser(app, "member")
  stranger = await registerUser(app, "stranger")
  const project = await createProject(app, owner)
  projectId = project.id
  const key = await issueKey(app, { accessToken: owner.accessToken, projectId })
  keyToken = key.token

  // 把 member 加进 owner 的组织（成为 member，非 owner）
  await request(app)
    .post(`/api/v1/orgs/${owner.org.id}/members`)
    .set("Authorization", `Bearer ${owner.accessToken}`)
    .send({ email: member.email, role: "member" })
    .expect(201)

  // 摄取一条 run + sample + constraint
  await ingest([
    {
      event_id: `${extRun}-run`,
      type: "run",
      data: {
        external_run_id: extRun,
        mode: "eval_only",
        status: "completed",
        metrics: { DR: 0.96, CPR: 0.91, avg_reward: 0.82, condR: 0.85, avg_time_ms: 500 },
        total_samples: 1,
      },
    },
    {
      event_id: `${extRun}-sample`,
      type: "sample",
      data: {
        external_run_id: extRun,
        external_sample_id: extSample,
        status: "pass",
        s_format: 1,
        s_common: 1,
        s_soft: 0.8,
        s_pref: 0.7,
        reward: 0.82,
      },
    },
    {
      event_id: `${extRun}-constraint`,
      type: "constraint",
      data: {
        external_run_id: extRun,
        external_sample_id: extSample,
        constraint_id: "c1",
        name: "has title",
        tier: "hard_gate",
        status: "pass",
        passed: true,
        score: 1,
        reason: "ok",
        duration_ms: 10,
      },
    },
  ])
})

describe("公开项目匿名访问（docs/arch/12 §3.5）", () => {
  it("未公开：匿名访问运行详情 → 401", async () => {
    const r = await request(app).get(`/api/v1/runs/${extRun}`)
    expect(r.status).toBe(401)
  })

  it("owner PATCH isPublic=true → 200 且生效", async () => {
    const r = await request(app)
      .patch(`/api/v1/projects/${projectId}`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ isPublic: true })
    expect(r.status).toBe(200)
    expect(r.body.project.isPublic).toBe(true)
  })

  it("公开后：匿名访问运行详情 → 200", async () => {
    const r = await request(app).get(`/api/v1/runs/${extRun}`)
    expect(r.status).toBe(200)
    expect(r.body.run.externalRunId).toBe(extRun)
    expect(r.body.run.samples.length).toBeGreaterThan(0)
    sampleDbId = r.body.run.samples[0].id
  })

  it("公开后：匿名访问样本详情 → 200", async () => {
    const r = await request(app).get(`/api/v1/runs/${extRun}/samples/${sampleDbId}`)
    expect(r.status).toBe(200)
    expect(r.body.sample.externalSampleId).toBe(extSample)
  })

  it("非成员 PATCH isPublic → 404（不泄露存在性）", async () => {
    const r = await request(app)
      .patch(`/api/v1/projects/${projectId}`)
      .set("Authorization", `Bearer ${stranger.accessToken}`)
      .send({ isPublic: false })
    expect(r.status).toBe(404)
  })

  it("member（非 owner）PATCH isPublic → 403", async () => {
    const r = await request(app)
      .patch(`/api/v1/projects/${projectId}`)
      .set("Authorization", `Bearer ${member.accessToken}`)
      .send({ isPublic: false })
    expect(r.status).toBe(403)
  })

  it("owner PATCH isPublic=false 后：匿名访问 → 401", async () => {
    await request(app)
      .patch(`/api/v1/projects/${projectId}`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ isPublic: false })
      .expect(200)
    const r = await request(app).get(`/api/v1/runs/${extRun}`)
    expect(r.status).toBe(401)
  })
})
