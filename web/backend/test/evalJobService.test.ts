/**
 * evalJobService 单测 — mock repository / 对象存储 / SCF，断言 submit 流程。
 */

import { beforeEach, describe, expect, it, vi } from "vitest"
import type { Tenant } from "../src/repositories/base.repository"

// vi.mock 工厂会被提升到顶部；用 vi.hoisted 让 mock 句柄同步提升，避免「未初始化」。
const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  updateScfRequestId: vi.fn(),
  findById: vi.fn(),
  put: vi.fn(),
  presignGet: vi.fn(),
  invokeScf: vi.fn(),
  cfg: { scfEnabled: false } as { scfEnabled: boolean },
}))

vi.mock("../src/config", () => ({ getConfig: () => mocks.cfg }))
vi.mock("../src/repositories/evalJob.repository", () => ({
  // service 用 `new EvalJobRepository(tenant)`；class mock 可被 new。
  EvalJobRepository: class {
    create = mocks.create
    updateScfRequestId = mocks.updateScfRequestId
    findById = mocks.findById
  },
}))
vi.mock("../src/infra/objectStorage", () => ({
  getObjectStorage: () => ({ put: mocks.put, presignGet: mocks.presignGet }),
}))
vi.mock("../src/infra/scf", () => ({ invokeScf: mocks.invokeScf }))

import { createEvalJobService } from "../src/services/evalJob.service"

const tenant: Tenant = {
  kind: "apikey",
  apiKeyId: "ak-1",
  projectId: "p-1",
  orgId: "o-1",
  scopes: ["ingest"],
}

describe("createEvalJobService.submit", () => {
  beforeEach(() => {
    mocks.create.mockReset()
    mocks.create.mockResolvedValue({})
    mocks.updateScfRequestId.mockReset()
    mocks.updateScfRequestId.mockResolvedValue(1)
    mocks.put.mockReset()
    mocks.put.mockResolvedValue({ md5: "x", size: 1 })
    mocks.presignGet.mockReset()
    mocks.presignGet.mockResolvedValue({ url: "http://presigned", expiresAt: 0 })
    mocks.invokeScf.mockReset()
    mocks.invokeScf.mockResolvedValue({ RequestId: "scf-rid" })
    mocks.cfg.scfEnabled = false
  })

  it("materializes, uploads, persists (queued) without SCF when disabled", async () => {
    const svc = createEvalJobService(tenant)
    const r = await svc.submit({
      filename: "lesson.md",
      fileBytes: Buffer.from("# hi"),
      ruleSetId: "coursework-quality",
    })

    expect(r.status).toBe("queued")
    expect(r.project_id).toBe("p-1")
    expect(r.job_id).toBeTruthy()
    expect(mocks.put).toHaveBeenCalledOnce()
    expect(mocks.presignGet).toHaveBeenCalledOnce()
    expect(mocks.create).toHaveBeenCalledOnce()
    expect(mocks.invokeScf).not.toHaveBeenCalled()

    const data = mocks.create.mock.calls[0]![0] as { scope: string }
    expect(data.scope).toBe("single")
  })

  it("invokes SCF and records RequestId when enabled (zip → unit)", async () => {
    mocks.cfg.scfEnabled = true
    const svc = createEvalJobService(tenant)
    const r = await svc.submit({
      filename: "unit.zip",
      fileBytes: Buffer.from([0x50, 0x4b, 0x03, 0x04]),
      ruleSetId: "coursework-vision",
    })

    expect(mocks.invokeScf).toHaveBeenCalledOnce()
    expect(mocks.updateScfRequestId).toHaveBeenCalledOnce()
    expect(r.scf_request_id).toBe("scf-rid")
    const data = mocks.create.mock.calls[0]![0] as { scope: string }
    expect(data.scope).toBe("unit")
  })
})
