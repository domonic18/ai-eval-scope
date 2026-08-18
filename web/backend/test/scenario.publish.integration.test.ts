/**
 * Phase 3 场景包发布 API 测试（POST /api/v1/scenarios/:id/packages，platform admin）。
 */

import { describe, it, expect, afterEach } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { registerUser } from "./helpers"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const SCENARIO_ID = `test-publish-${Date.now()}`
const USER_EMAIL: string[] = []
const ORG_SLUGS: string[] = []

afterEach(async () => {
  await prisma.scenarioPackage.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
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

describe("POST /api/v1/scenarios/:id/packages", () => {
  it("rejects without admin (403)", async () => {
    const app = createApp()
    const u = await registerUser(app, "pub-noadmin")
    USER_EMAIL.push(u.email)
    ORG_SLUGS.push(u.org.slug)
    // 普通用户（非 admin）
    const res = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/packages`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send({ asset_id: "x", version: "1.0.0" })
    expect(res.status).toBe(403)
  })

  it("publishes a package version as admin (201)", async () => {
    const app = createApp()
    const u = await registerUser(app, "pub-admin")
    USER_EMAIL.push(u.email)
    ORG_SLUGS.push(u.org.slug)
    // 提升为平台 admin
    await prisma.user.update({ where: { email: u.email }, data: { role: "admin" } })

    const body = {
      asset_id: "quality",
      version: "1.0.0",
      labels: ["production"],
      name: "测试场景",
      description: "publish 测试",
      content: { manifest: { id: "quality" } },
    }
    const res = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/packages`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send(body)
    expect(res.status).toBe(201)
    expect(res.body.package.scenarioId).toBe(SCENARIO_ID)

    // DB 落库
    const pkg = await prisma.scenarioPackage.findUnique({
      where: {
        scenarioId_assetId_version: {
          scenarioId: SCENARIO_ID,
          assetId: "quality",
          version: "1.0.0",
        },
      },
    })
    expect(pkg?.labels).toContain("production")
    expect(pkg?.createdBy).toBe(u.user.id)
  })

  it("rejects re-publishing an existing version (409 immutable)", async () => {
    const app = createApp()
    const u = await registerUser(app, "pub-imm")
    USER_EMAIL.push(u.email)
    ORG_SLUGS.push(u.org.slug)
    await prisma.user.update({ where: { email: u.email }, data: { role: "admin" } })

    const body = {
      asset_id: "quality",
      version: "1.0.0",
      labels: ["production"],
      content: { manifest: { id: "quality" } },
    }
    const first = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/packages`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send(body)
    expect(first.status).toBe(201)

    // 同版本号重发（改 labels）→ 409（版本不可变，不再 upsert 覆盖）
    const again = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/packages`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send({ ...body, labels: ["staging"] })
    expect(again.status).toBe(409)

    // 原行未被覆盖
    const pkg = await prisma.scenarioPackage.findUnique({
      where: {
        scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: "quality", version: "1.0.0" },
      },
    })
    expect(pkg?.labels).toEqual(["production"])
  })

  it("rejects missing fields (400)", async () => {
    const app = createApp()
    const u = await registerUser(app, "pub-bad")
    USER_EMAIL.push(u.email)
    ORG_SLUGS.push(u.org.slug)
    await prisma.user.update({ where: { email: u.email }, data: { role: "admin" } })
    const res = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/packages`)
      .set("Authorization", `Bearer ${u.accessToken}`)
      .send({ labels: ["latest"] })
    expect(res.status).toBe(400)
  })
})
