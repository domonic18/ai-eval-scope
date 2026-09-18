/**
 * run 导出契约集成测试（docs/arch/09 §9.8）：
 * 真实 minio 造对象 → GET /runs/:id/export → zip 魔数 + manifest/summary/条目名字节断言。
 * 鉴权矩阵：匿名私有 401 / 跨 org 404 / 公开项目匿名 200（与运行详情同语义）。
 */
import request from "supertest"
import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { createApp } from "../src/server"
import { getPrisma } from "../src/infra/prisma"
import { getObjectStorage } from "../src/infra/objectStorage"
import { hashPassword, issueAccessTokenResult } from "../src/infra/crypto"

const app = createApp()
const prisma = getPrisma()

const tag = Math.random().toString(36).slice(2, 8)
let ownerToken = "" // 私有项目 org owner
let outsiderToken = "" // 他组织用户
let ownerUserId = ""
let outsiderUserId = ""
let orgId = ""
let projectId = ""
let publicProjectId = ""
let runDbId = ""
let sampleDbId = ""
const objectKeys: string[] = []

async function seedRun(projectIdRef: string, extRunId: string) {
  const run = await prisma.run.create({
    data: {
      projectId: projectIdRef,
      externalRunId: extRunId,
      mode: "eval_only",
      scenarioId: `exp_scn_${tag}`,
      metrics: { reward: 0.9, delivery_rate: 1 },
      totalSamples: 1,
      summaryReport: { overview: "导出契约冒烟" },
    },
  })
  const sample = await prisma.sample.create({
    data: {
      runId: run.id,
      projectId: projectIdRef,
      externalSampleId: `exp_s_${tag}`,
      status: "completed",
      reward: 0.9,
    },
  })
  // 制品对象：真实写入 minio（输出 ×2 同名去重 + 会话 transcript + 无样本归属 trace）
  const storage = getObjectStorage()
  const mk = (n: string) => `test-export/${tag}/${n}`
  const spec = [
    { key: mk("out1.md"), name: "answer.md", kind: "output", sampleId: sample.id },
    { key: mk("out2.md"), name: "answer.md", kind: "output", sampleId: sample.id },
    { key: mk("sess.md"), name: "transcript.md", kind: "transcript", sampleId: sample.id },
    { key: mk("trace.json"), name: "trace.json", kind: "trace", sampleId: null },
  ] as const
  for (const s of spec) {
    await storage.put({ key: s.key, body: Buffer.from(`content-of-${s.name}`, "utf8"), contentType: "text/markdown" })
    objectKeys.push(s.key)
    await prisma.artifact.create({
      data: {
        projectId: projectIdRef,
        runId: run.id,
        sampleId: s.sampleId,
        kind: s.kind,
        objectKey: s.key,
        storage: "minio",
        contentType: "text/markdown",
        sizeBytes: BigInt(`content-of-${s.name}`.length),
        md5: null,
        originalName: s.name,
      },
    })
  }
  return { run, sample }
}

beforeAll(async () => {
  const owner = await prisma.user.create({
    data: { email: `expown_${tag}@example.com`, passwordHash: await hashPassword("password123") },
  })
  const outsider = await prisma.user.create({
    data: { email: `expout_${tag}@example.com`, passwordHash: await hashPassword("password123") },
  })
  ownerUserId = owner.id
  outsiderUserId = outsider.id
  ownerToken = issueAccessTokenResult({ userId: owner.id }).access_token
  outsiderToken = issueAccessTokenResult({ userId: outsider.id }).access_token

  const org = await prisma.organization.create({
    data: {
      name: `exp-org-${tag}`,
      slug: `exp-org-${tag}`,
      createdBy: owner.id,
      members: { create: { userId: owner.id, role: "owner" } },
    },
  })
  orgId = org.id
  const proj = await prisma.project.create({
    data: { name: `exp-proj-${tag}`, slug: `exp-${tag}`, orgId: org.id, createdBy: owner.id },
  })
  projectId = proj.id
  const pub = await prisma.project.create({
    data: {
      name: `exp-pub-${tag}`,
      slug: `exp-pub-${tag}`,
      orgId: org.id,
      createdBy: owner.id,
      isPublic: true,
    },
  })
  publicProjectId = pub.id

  const seeded = await seedRun(proj.id, `exp_run_${tag}`)
  runDbId = seeded.run.id
  sampleDbId = seeded.sample.id
  await seedRun(pub.id, `exp_pub_run_${tag}`)
})

afterAll(async () => {
  await getObjectStorage().deleteObjects(objectKeys).catch(() => undefined)
  await prisma.run.deleteMany({ where: { id: runDbId } })
  await prisma.project.deleteMany({ where: { id: { in: [projectId, publicProjectId] } } })
  await prisma.organization.deleteMany({ where: { id: orgId } })
  await prisma.user.deleteMany({ where: { id: { in: [ownerUserId, outsiderUserId] } } })
  void sampleDbId
})

describe("GET /api/v1/runs/:id/export（§9.8 导出契约）", () => {
  it("私有项目匿名 → 401", async () => {
    const r = await request(app).get(`/api/v1/runs/${runDbId}/export`)
    expect(r.status).toBe(401)
  })

  it("跨 org 用户 → 404（不泄露存在性）", async () => {
    const r = await request(app)
      .get(`/api/v1/runs/${runDbId}/export`)
      .set("Authorization", `Bearer ${outsiderToken}`)
    expect(r.status).toBe(404)
  })

  it("owner → 200 zip：魔数 + manifest.json + summary.md + 样本分组条目 + 同名去重", async () => {
    const r = await request(app)
      .get(`/api/v1/runs/${runDbId}/export`)
      .responseType("blob")
      .set("Authorization", `Bearer ${ownerToken}`)
    expect(r.status).toBe(200)
    expect(r.headers["content-type"]).toBe("application/zip")
    expect(r.headers["content-disposition"]).toContain(".zip")
    const body = r.body as Buffer
    // zip 魔数 PK\x03\x04
    expect(body.length).toBeGreaterThan(4)
    expect(body[0]).toBe(0x50)
    expect(body[1]).toBe(0x4b)
    expect(body[2]).toBe(0x03)
    expect(body[3]).toBe(0x04)
    // zip 本地头明文文件名，直接字节串断言（零新依赖）
    const ascii = body.toString("latin1")
    expect(ascii).toContain("manifest.json")
    expect(ascii).toContain("summary.md")
    expect(ascii).toContain("summary.json")
    // transcript 置样本根；output/trace 按样本/kind 分组
    expect(ascii).toContain(`samples/exp_s_${tag}/transcript.md`)
    expect(ascii).toContain(`samples/exp_s_${tag}/output/answer.md`)
    expect(ascii).toContain(`run/trace/trace.json`)
    // 同名去重：两个 answer.md → 第二个带制品 id 后缀
    expect(ascii).toContain("answer-")
  })

  it("公开项目匿名 → 200（与运行详情同语义）", async () => {
    const r = await request(app)
      .get(`/api/v1/runs/exp_pub_run_${tag}/export`)
      .responseType("blob")
    expect(r.status).toBe(200)
    expect(r.body[0]).toBe(0x50)
  })
})
