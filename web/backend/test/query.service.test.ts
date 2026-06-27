/**
 * QueryService.deleteRun 单元测试（不依赖真实 DB / 不联网）。
 *
 * mock 依赖：QueryRepository（runDetail/deleteRun）、objectStorage（deleteObjects）、
 *           logger、AuditService。覆盖：正常链路、对象存储 best-effort、无制品、run 不存在 404。
 */

import { describe, it, expect, beforeEach, vi } from "vitest"

// ── mock 依赖（vi.hoisted 让 mock 工厂与测试共享可变状态）──
const mocks = vi.hoisted(() => {
  const repo = {
    requireOrg: vi.fn(() => "org1"),
    runDetail: vi.fn(),
    deleteRun: vi.fn(),
  }
  const storage = { deleteObjects: vi.fn() }
  const audit = { log: vi.fn() }
  return { repo, storage, audit }
})

vi.mock("../src/repositories/query.repository", () => ({
  // createQueryService 内 `new QueryRepository(tenant)` 得到实例
  QueryRepository: class MockQueryRepository {
    requireOrg = mocks.repo.requireOrg
    runDetail = mocks.repo.runDetail
    deleteRun = mocks.repo.deleteRun
  },
}))

vi.mock("../src/infra/objectStorage", () => ({
  getObjectStorage: () => mocks.storage,
}))

vi.mock("../src/infra/logger", () => ({
  getLogger: () => ({ warn: vi.fn(), info: vi.fn(), error: vi.fn() }),
}))

vi.mock("../src/services/audit.service", () => ({
  AuditService: { log: mocks.audit.log },
}))

import { createQueryService } from "../src/services/query.service"
import { PlatformError } from "../src/middleware/errorHandler"
import type { Tenant } from "../src/repositories/base.repository"

const tenant: Tenant = {
  kind: "user",
  userId: "u1",
  orgId: "org1",
  projectId: "proj1",
  role: "owner",
}

const run = { id: "r1", externalRunId: "ext-1", projectId: "proj1" }

beforeEach(() => {
  vi.clearAllMocks()
  mocks.repo.runDetail.mockResolvedValue(run)
  mocks.repo.deleteRun.mockResolvedValue(["k1", "k2"])
  mocks.storage.deleteObjects.mockResolvedValue(undefined)
  mocks.audit.log.mockResolvedValue(undefined)
})

describe("QueryService.deleteRun", () => {
  it("删 DB + 清对象存储 + 写审计（正常链路）", async () => {
    const svc = createQueryService(tenant)
    await svc.deleteRun("r1")

    expect(mocks.repo.runDetail).toHaveBeenCalledWith("proj1", "r1")
    expect(mocks.repo.deleteRun).toHaveBeenCalledWith("r1")
    expect(mocks.storage.deleteObjects).toHaveBeenCalledWith(["k1", "k2"])
    expect(mocks.audit.log).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "run.delete",
        targetType: "run",
        targetId: "r1",
        actorUserId: "u1",
        orgId: "org1",
      }),
    )
  })

  it("对象存储删除失败不阻断（best-effort），审计仍执行", async () => {
    mocks.storage.deleteObjects.mockRejectedValue(new Error("s3 down"))
    const svc = createQueryService(tenant)

    await expect(svc.deleteRun("r1")).resolves.toBeUndefined()
    expect(mocks.audit.log).toHaveBeenCalled()
  })

  it("无制品时不调对象存储删除", async () => {
    mocks.repo.deleteRun.mockResolvedValue([])
    const svc = createQueryService(tenant)

    await svc.deleteRun("r1")
    expect(mocks.storage.deleteObjects).not.toHaveBeenCalled()
  })

  it("run 不存在 → 404 且不执行删除", async () => {
    mocks.repo.runDetail.mockResolvedValue(null)
    const svc = createQueryService(tenant)

    let err: unknown
    try {
      await svc.deleteRun("missing")
    } catch (e) {
      err = e
    }
    expect(err).toBeInstanceOf(PlatformError)
    expect((err as PlatformError).status).toBe(404)
    expect((err as PlatformError).code).toBe("NOT_FOUND")
    expect(mocks.repo.deleteRun).not.toHaveBeenCalled()
    expect(mocks.storage.deleteObjects).not.toHaveBeenCalled()
  })
})
