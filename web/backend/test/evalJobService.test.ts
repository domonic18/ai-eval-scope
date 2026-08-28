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

  it("leaves packageRef null when not provided (no courseware auto-default, S2-D)", async () => {
    const svc = createEvalJobService(tenant)
    await svc.submit({ filename: "lesson.md", fileBytes: Buffer.from("# hi"), ruleSetId: "coursework-quality" })
    const data = mocks.create.mock.calls[0]![0] as { packageRef: string | null }
    expect(data.packageRef).toBeNull()
  })

  it("uses explicit packageRef when provided (S2-D)", async () => {
    const svc = createEvalJobService(tenant)
    await svc.submit({
      filename: "lesson.md",
      fileBytes: Buffer.from("# hi"),
      ruleSetId: "coursework-quality",
      packageRef: "courseware/courseware:staging",
    })
    const data = mocks.create.mock.calls[0]![0] as { packageRef: string | null }
    expect(data.packageRef).toBe("courseware/courseware:staging")
  })

  it("leaves packageRef null for non-courseware rule sets without explicit ref (S2-D)", async () => {
    const svc = createEvalJobService(tenant)
    await svc.submit({ filename: "lesson.md", fileBytes: Buffer.from("# hi"), ruleSetId: "custom-rs" })
    const data = mocks.create.mock.calls[0]![0] as { packageRef: string | null }
    expect(data.packageRef).toBeNull()
  })

  it("forwards explicit package_ref in SCF payload (S2-D)", async () => {
    mocks.cfg.scfEnabled = true
    const svc = createEvalJobService(tenant)
    await svc.submit({
      filename: "lesson.md",
      fileBytes: Buffer.from("# hi"),
      ruleSetId: "coursework-quality",
      packageRef: "courseware/courseware:production",
    })
    const payload = mocks.invokeScf.mock.calls[0]![0] as { package_ref?: string | null }
    expect(payload.package_ref).toBe("courseware/courseware:production")
  })
})

describe("createEvalJobService.refreshInputUrl", () => {
  beforeEach(() => {
    mocks.findById.mockReset()
    mocks.presignGet.mockReset()
    mocks.presignGet.mockResolvedValue({ url: "http://presigned-fresh", expiresAt: 1800 })
  })

  it("re-signs a fresh presigned GET for the job's input object", async () => {
    // executor 领取任务后重签：提交时签发的 URL ≤15min，队列积压会拖过期（B2b）
    mocks.findById.mockResolvedValue({ id: "job-1", inputObjectKey: "projects/p-1/eval/jobs/job-1/input.md" })

    const svc = createEvalJobService(tenant)
    const r = await svc.refreshInputUrl("job-1")

    expect(mocks.findById).toHaveBeenCalledWith("job-1")
    expect(mocks.presignGet).toHaveBeenCalledOnce()
    expect(mocks.presignGet).toHaveBeenCalledWith({ key: "projects/p-1/eval/jobs/job-1/input.md" })
    expect(r).toEqual({ url: "http://presigned-fresh", expires_at: 1800 })
  })

  it("returns null without presigning when job is not in this tenant's project", async () => {
    // findById 带 projectId 租户过滤：他项目 job 查不到 → 404 语义，不泄露他项目对象
    mocks.findById.mockResolvedValue(null)

    const svc = createEvalJobService(tenant)
    const r = await svc.refreshInputUrl("job-of-other-project")

    expect(r).toBeNull()
    expect(mocks.presignGet).not.toHaveBeenCalled()
  })
})
