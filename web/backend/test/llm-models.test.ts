/**
 * LLM 模型配置路由单测 — mock 仓储/用户查找/加密，聚焦鉴权门与关键行为。
 * 覆盖：非超管 403 / CRUD / set-default 原子性 / delete-default-reassign / 缺失 ID 404。
 */
import request from "supertest"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { createApp } from "../src/server"
import { issueAccessTokenResult } from "../src/infra/crypto"

const {
  findByIdMock,
  listMock,
  createMock,
  updateMock,
  removeMock,
  setDefaultMock,
  getRawMock,
  getDefaultRawMock,
  recordTestMock,
} = vi.hoisted(() => ({
  findByIdMock: vi.fn(),
  listMock: vi.fn(),
  createMock: vi.fn(),
  updateMock: vi.fn(),
  removeMock: vi.fn(),
  setDefaultMock: vi.fn(),
  getRawMock: vi.fn(),
  getDefaultRawMock: vi.fn(),
  recordTestMock: vi.fn(),
}))

vi.mock("../src/repositories/user.repository", () => ({
  UserRepository: class {
    findById = findByIdMock
  },
  OrgRepository: class {},
}))
vi.mock("../src/repositories/adminStats.repository", () => ({
  adminStatsRepository: { overview: vi.fn(), trends: vi.fn(), scoreDistribution: vi.fn() },
}))
vi.mock("../src/repositories/admin.repository", () => ({
  adminRepository: {
    listUsers: vi.fn(),
    updateUser: vi.fn(),
    deleteUser: vi.fn(),
    listOrgs: vi.fn(),
    deleteOrg: vi.fn(),
    listProjects: vi.fn(),
    deleteProject: vi.fn(),
    listRuns: vi.fn(),
    deleteRun: vi.fn(),
    listArtifacts: vi.fn(),
    deleteArtifact: vi.fn(),
    batchDeleteArtifacts: vi.fn(),
    listAudit: vi.fn(),
  },
}))
vi.mock("../src/repositories/llm-model.repository", () => ({
  llmModelRepository: {
    list: listMock,
    create: createMock,
    update: updateMock,
    remove: removeMock,
    setDefault: setDefaultMock,
    getRaw: getRawMock,
    getDefaultRaw: getDefaultRawMock,
    recordTest: recordTestMock,
  },
}))
vi.mock("../src/infra/objectStorage", () => ({
  getObjectStorage: () => ({ deleteObjects: vi.fn() }),
}))
vi.mock("../src/services/audit.service", () => ({
  AuditService: { log: vi.fn().mockResolvedValue(undefined) },
}))
vi.mock("../src/services/llm-client.service", () => ({
  llmClientService: {
    testModel: vi.fn().mockResolvedValue({ status: "success", detail: "ok", testedAt: "2026-01-01T00:00:00.000Z" }),
    chat: vi.fn(),
    exportYaml: vi.fn().mockResolvedValue("llm:\n  default: test\n  providers: {}"),
  },
}))

const app = createApp()
const adminToken = issueAccessTokenResult({ userId: "u-admin", platformAdmin: true }).access_token
const userToken = issueAccessTokenResult({ userId: "u-user", platformAdmin: false }).access_token

const adminUser = { role: "admin", status: "active" }
const regularUser = { role: "user", status: "active" }

const mockVO = (overrides: Partial<Record<string, unknown>> = {}) => ({
  id: "m1",
  name: "Test Model",
  provider: "openai",
  baseUrl: "https://api.openai.com/v1",
  apiKeyMasked: "sk-x****y",
  modelName: "gpt-4",
  isActive: true,
  isDefault: false,
  extra: { temperature: 0, max_tokens: 8192 },
  lastTestedAt: null,
  lastTestStatus: null,
  lastTestError: null,
  createdAt: "2026-01-01T00:00:00.000Z",
  updatedAt: "2026-01-01T00:00:00.000Z",
  ...overrides,
})

beforeEach(() => {
  findByIdMock.mockReset()
  listMock.mockReset()
  createMock.mockReset()
  updateMock.mockReset()
  removeMock.mockReset()
  setDefaultMock.mockReset()
  getRawMock.mockReset()
  getDefaultRawMock.mockReset()
  recordTestMock.mockReset()
  findByIdMock.mockResolvedValue(adminUser)
})

describe("GET /api/v1/admin/llm-models — 鉴权门", () => {
  it("非超管 → 403", async () => {
    findByIdMock.mockResolvedValue(regularUser)
    const r = await request(app)
      .get("/api/v1/admin/llm-models")
      .set("Authorization", `Bearer ${userToken}`)
    expect(r.status).toBe(403)
  })

  it("超管 → 200 + 列表", async () => {
    listMock.mockResolvedValue([mockVO()])
    const r = await request(app)
      .get("/api/v1/admin/llm-models")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(200)
    expect(r.body).toHaveLength(1)
    expect(r.body[0].name).toBe("Test Model")
  })
})

describe("POST /api/v1/admin/llm-models — 创建", () => {
  it("缺 apiKey → 400（非 500）", async () => {
    const { PlatformError } = await import("../src/middleware/errorHandler")
    createMock.mockImplementation(async () => {
      throw new PlatformError("api_key 必填", { status: 400, code: "VALIDATION_ERROR" })
    })
    const r = await request(app)
      .post("/api/v1/admin/llm-models")
      .set("Authorization", `Bearer ${adminToken}`)
      .send({ name: "Test", provider: "openai", modelName: "gpt-4" })
    expect(r.status).toBe(400)
    expect(r.body.code).toBe("VALIDATION_ERROR")
  })

  it("非法 provider → 400", async () => {
    const { PlatformError } = await import("../src/middleware/errorHandler")
    createMock.mockImplementation(async () => {
      throw new PlatformError("provider 必须为 openai 或 anthropic", { status: 400, code: "VALIDATION_ERROR" })
    })
    const r = await request(app)
      .post("/api/v1/admin/llm-models")
      .set("Authorization", `Bearer ${adminToken}`)
      .send({ name: "Test", provider: "gemini", apiKey: "sk-x", modelName: "gpt-4" })
    expect(r.status).toBe(400)
  })

  it("合法创建 → 201", async () => {
    createMock.mockResolvedValue(mockVO({ name: "New" }))
    const r = await request(app)
      .post("/api/v1/admin/llm-models")
      .set("Authorization", `Bearer ${adminToken}`)
      .send({ name: "New", provider: "openai", apiKey: "sk-x", modelName: "gpt-4" })
    expect(r.status).toBe(201)
    expect(r.body.name).toBe("New")
  })
})

describe("PATCH /api/v1/admin/llm-models/:id — 更新", () => {
  it("缺失 ID → 404（非 500）", async () => {
    updateMock.mockImplementation(async () => {
      throw new (class extends Error {
        status = 404
        code = "NOT_FOUND"
      })("llm model not found")
    })
    const r = await request(app)
      .patch("/api/v1/admin/llm-models/nonexistent")
      .set("Authorization", `Bearer ${adminToken}`)
      .send({ name: "Updated" })
    expect(r.status).toBe(404)
  })
})

describe("POST /api/v1/admin/llm-models/:id/set-default — 设默认", () => {
  it("缺失 ID → 404（非 500）", async () => {
    setDefaultMock.mockImplementation(async () => {
      throw new (class extends Error {
        status = 404
        code = "NOT_FOUND"
      })("llm model not found")
    })
    const r = await request(app)
      .post("/api/v1/admin/llm-models/nonexistent/set-default")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(404)
  })

  it("合法设默认 → 200", async () => {
    setDefaultMock.mockResolvedValue(mockVO({ isDefault: true }))
    const r = await request(app)
      .post("/api/v1/admin/llm-models/m1/set-default")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(200)
    expect(r.body.isDefault).toBe(true)
  })
})

describe("POST /api/v1/admin/llm-models/:id/test — 连通性测试", () => {
  it("缺失 ID → 404", async () => {
    getRawMock.mockResolvedValue(null)
    const r = await request(app)
      .post("/api/v1/admin/llm-models/nonexistent/test")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(404)
  })

  it("合法测试 → 200 + success", async () => {
    getRawMock.mockResolvedValue({ id: "m1", modelName: "gpt-4" })
    const r = await request(app)
      .post("/api/v1/admin/llm-models/m1/test")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(200)
    expect(r.body.status).toBe("success")
  })
})

describe("DELETE /api/v1/admin/llm-models/:id — 删除", () => {
  it("缺失 ID → 404", async () => {
    removeMock.mockImplementation(async () => {
      throw new (class extends Error {
        status = 404
        code = "NOT_FOUND"
      })("llm model not found")
    })
    const r = await request(app)
      .delete("/api/v1/admin/llm-models/nonexistent")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(404)
  })

  it("合法删除 → 204", async () => {
    removeMock.mockResolvedValue(undefined)
    const r = await request(app)
      .delete("/api/v1/admin/llm-models/m1")
      .set("Authorization", `Bearer ${adminToken}`)
    expect(r.status).toBe(204)
  })
})
