/**
 * 超管后台集成测试 —— 直接经 prisma 建真实用户，supertest 打真实路由 + 真实 DB。
 * 覆盖：platformAdminGuard（403/200/禁用即时生效）、用户列表、提权、防自锁、统计聚合 SQL。
 * 不复用 helpers.registerUser（其依赖已废弃的 register 返回 org）。
 */
import request from "supertest"
import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { createApp } from "../src/server"
import { getPrisma } from "../src/infra/prisma"
import { hashPassword, issueTokenPair } from "../src/infra/crypto"

const app = createApp()
const prisma = getPrisma()

const tag = Math.random().toString(36).slice(2, 8)
const adminEmail = `adm_${tag}@example.com`
const userEmail = `usr_${tag}@example.com`
let adminId = ""
let userId = ""
let adminToken = ""
let userToken = ""

beforeAll(async () => {
  const admin = await prisma.user.create({
    data: { email: adminEmail, passwordHash: await hashPassword("password123"), role: "admin" },
  })
  const user = await prisma.user.create({
    data: { email: userEmail, passwordHash: await hashPassword("password123"), role: "user" },
  })
  adminId = admin.id
  userId = user.id
  adminToken = issueTokenPair({ userId: adminId, platformAdmin: true }).access_token
  userToken = issueTokenPair({ userId, platformAdmin: false }).access_token
})

afterAll(async () => {
  await prisma.user.deleteMany({ where: { id: { in: [adminId, userId] } } })
})

describe("超管后台 /api/v1/admin", () => {
  it("普通用户 → 403 FORBIDDEN", async () => {
    const r = await request(app)
      .get("/api/v1/admin/stats/overview")
      .set("Authorization", `Bearer ${userToken}`)
    expect(r.status).toBe(403)
    expect(r.body.code).toBe("FORBIDDEN")
  })

  it("超管 → 200 + overview 聚合结构", async () => {
    const r = await request(app)
      .get("/api/v1/admin/stats/overview")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(200)
    expect(r.body.users).toBeDefined()
    expect(r.body.runs).toBeDefined()
    expect(r.body.artifacts).toBeDefined()
    // 至少包含本测试创建的两个用户
    expect(r.body.users.total).toBeGreaterThanOrEqual(2)
  })

  it("超管 → 用户列表含分页", async () => {
    const r = await request(app)
      .get(`/api/v1/admin/users?search=${tag}`)
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(200)
    expect(r.body.total).toBeGreaterThanOrEqual(2)
    expect(Array.isArray(r.body.items)).toBe(true)
  })

  it("超管 → trends / score-distribution 200（聚合 SQL 不报错）", async () => {
    const t = await request(app)
      .get("/api/v1/admin/stats/trends?limit=10")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(t.status).toBe(200)
    const d = await request(app)
      .get("/api/v1/admin/stats/score-distribution")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(d.status).toBe(200)
  })

  it("提权普通用户 → admin（DB 反映）", async () => {
    const r = await request(app)
      .patch(`/api/v1/admin/users/${userId}`)
      .set("Authorization", `Bearer ${adminToken}`)
      .send({ role: "admin" })
    expect(r.status).toBe(200)
    expect(r.body.role).toBe("admin")
    const row = await prisma.user.findUnique({ where: { id: userId } })
    expect(row!.role).toBe("admin")
  })

  it("防自锁：降权自己 → 400 SELF_LOCKOUT", async () => {
    const r = await request(app)
      .patch(`/api/v1/admin/users/${adminId}`)
      .set("Authorization", `Bearer ${adminToken}`)
      .send({ role: "user" })
    expect(r.status).toBe(400)
    expect(r.body.code).toBe("SELF_LOCKOUT")
  })

  it("禁用即时生效：禁用超管后其 token 再请求 → 403", async () => {
    // 用另一个超管禁用 adminId（先恢复 user 角色冲突已无，admin 仍 admin）
    // 这里改用：把 user 提为 admin，再用 admin 禁用原 admin
    await prisma.user.update({ where: { id: userId }, data: { role: "admin" } })
    const r = await request(app)
      .patch(`/api/v1/admin/users/${adminId}`)
      .set("Authorization", `Bearer ${issueTokenPair({ userId, platformAdmin: true }).access_token}`)
      .send({ status: "disabled" })
    expect(r.status).toBe(200)
    const r2 = await request(app)
      .get("/api/v1/admin/stats/overview")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r2.status).toBe(403) // DB 鉴权即时反映 disabled
  })
})
