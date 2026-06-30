/**
 * 超管后台路由单测 — mock 仓储/用户查找，聚焦鉴权门与关键行为（不依赖 DB）。
 *  覆盖：非超管 403 / 超管 200 / 禁用超管 403 / 用户列表 / 防自锁。
 */
import request from "supertest"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { createApp } from "../src/server"
import { issueTokenPair } from "../src/infra/crypto"

const { findByIdMock, overviewMock, listUsersMock, updateUserMock } = vi.hoisted(() => ({
  findByIdMock: vi.fn(),
  overviewMock: vi.fn(),
  listUsersMock: vi.fn(),
  updateUserMock: vi.fn(),
}))

vi.mock("../src/repositories/user.repository", () => ({
  // adminGuard / auth.service：new UserRepository().findById(...)
  UserRepository: class {
    findById = findByIdMock
  },
  OrgRepository: class {},
}))
vi.mock("../src/repositories/adminStats.repository", () => ({
  adminStatsRepository: { overview: overviewMock, trends: vi.fn(), scoreDistribution: vi.fn() },
}))
vi.mock("../src/repositories/admin.repository", () => ({
  adminRepository: { listUsers: listUsersMock, updateUser: updateUserMock },
}))

const app = createApp()
const adminId = "u-admin"
const adminToken = issueTokenPair({ userId: adminId, platformAdmin: true }).access_token

const adminUser = { role: "admin", status: "active" }
const regularUser = { role: "user", status: "active" }
const disabledAdmin = { role: "admin", status: "disabled" }

beforeEach(() => {
  findByIdMock.mockReset()
  overviewMock.mockReset()
  listUsersMock.mockReset()
  updateUserMock.mockReset()
})

describe("GET /api/v1/admin/stats/overview — 鉴权门", () => {
  it("非超管 → 403", async () => {
    findByIdMock.mockResolvedValue(regularUser)
    const token = issueTokenPair({ userId: "u-other", platformAdmin: false }).access_token
    const r = await request(app)
      .get("/api/v1/admin/stats/overview")
      .set("Authorization", `Bearer ${token}`)
    expect(r.status).toBe(403)
    expect(r.body.code).toBe("FORBIDDEN")
  })

  it("超管 → 200 + overview 结构", async () => {
    findByIdMock.mockResolvedValue(adminUser)
    overviewMock.mockResolvedValue({
      users: { total: 5, active: 4, disabled: 1, admins: 1 },
      orgs: 2,
      projects: { total: 3, archived: 0 },
      runs: { total: 10, completed: 9, failed: 1, pending: 0 },
      samples: 40,
      artifacts: { total: 100, storageBytes: 5000 },
    })
    const r = await request(app)
      .get("/api/v1/admin/stats/overview")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(200)
    expect(r.body.users.admins).toBe(1)
    expect(r.body.runs.total).toBe(10)
  })

  it("已禁用超管 → 403（DB 鉴权即时生效）", async () => {
    findByIdMock.mockResolvedValue(disabledAdmin)
    const r = await request(app)
      .get("/api/v1/admin/stats/overview")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(403)
  })
})

describe("GET /api/v1/admin/users", () => {
  it("超管 → 200 + 分页结构", async () => {
    findByIdMock.mockResolvedValue(adminUser)
    listUsersMock.mockResolvedValue({
      items: [{ id: "u1", email: "a@b.c", role: "user", status: "active" }],
      total: 1,
      page: 1,
      size: 50,
    })
    const r = await request(app)
      .get("/api/v1/admin/users")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(200)
    expect(r.body.items[0].email).toBe("a@b.c")
    expect(r.body.total).toBe(1)
  })
})

describe("PATCH /api/v1/admin/users/:id — 防自锁", () => {
  it("降权自己 → 400 SELF_LOCKOUT（且不调用 updateUser）", async () => {
    findByIdMock.mockResolvedValue(adminUser)
    const r = await request(app)
      .patch(`/api/v1/admin/users/${adminId}`)
      .set("Authorization", `Bearer ${adminToken}`)
      .send({ role: "user" })
    expect(r.status).toBe(400)
    expect(r.body.code).toBe("SELF_LOCKOUT")
    expect(updateUserMock).not.toHaveBeenCalled()
  })

  it("禁用自己 → 400 SELF_LOCKOUT", async () => {
    findByIdMock.mockResolvedValue(adminUser)
    const r = await request(app)
      .patch(`/api/v1/admin/users/${adminId}`)
      .set("Authorization", `Bearer ${adminToken}`)
      .send({ status: "disabled" })
    expect(r.status).toBe(400)
    expect(r.body.code).toBe("SELF_LOCKOUT")
  })
})
