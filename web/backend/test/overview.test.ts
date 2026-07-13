/**
 * overview 速览单测（docs/arch/12 §6.6）：
 *  - buildJobOverview 纯函数：verdict / summary / dimension_pass / items / failures
 *  - createEvalJobService.overview：mock 仓储，覆盖 未完成→空 items / completed→聚合 / run 缺失
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { Tenant } from "../src/repositories/base.repository"
import { buildJobOverview, createEvalJobService } from "../src/services/evalJob.service"

const mocks = vi.hoisted(() => ({
  findById: vi.fn(),
  runOverview: vi.fn(),
  cfg: { scfEnabled: false },
}))

vi.mock("../src/config", () => ({ getConfig: () => mocks.cfg }))
vi.mock("../src/repositories/evalJob.repository", () => ({
  EvalJobRepository: class {
    findById = mocks.findById
  },
}))
vi.mock("../src/repositories/query.repository", () => ({
  QueryRepository: class {
    runOverview = mocks.runOverview
  },
}))
vi.mock("../src/infra/objectStorage", () => ({ getObjectStorage: () => ({}) }))
vi.mock("../src/infra/scf", () => ({ invokeScf: vi.fn() }))

const tenant: Tenant = {
  kind: "apikey",
  apiKeyId: "ak",
  projectId: "p-1",
  orgId: "o-1",
  scopes: ["ingest"],
}

const base = {
  job_id: "j1",
  run_id: "r1",
  status: "completed",
  web_run_url: "http://x/run/r1",
  error: null,
}

describe("buildJobOverview (pure)", () => {
  it("verdict=fail when a hard_gate constraint failed; 聚合 summary/dimension_pass/items", () => {
    const run = {
      externalRunId: "r1",
      dr: 0.99,
      cpr: 0.95,
      condR: 0.9,
      avgReward: 0.9,
      avgTimeMs: 100,
      totalSamples: 2,
      thresholds: null,
      samples: [
        {
          id: "s1",
          externalSampleId: "A",
          status: "fail",
          reward: 0.1,
          sFormat: -3,
          sCommon: 0,
          sSoft: 0.5,
          sPref: 0.4,
          constraintResults: [
            {
              name: "格式门禁",
              reason: "缺少 <html> 根标签",
              tier: "hard_gate",
              details: {
                dimensions: [{ issues: [{ desc: "缺 <html> 根标签", severity: "high" }] }],
                source_files: [{ filename: "index.html" }],
              },
            },
          ],
        },
        {
          id: "s2",
          externalSampleId: "B",
          status: "pass",
          reward: 0.95,
          sFormat: 1,
          sCommon: 1,
          sSoft: 0.9,
          sPref: 0.8,
          constraintResults: [],
        },
      ],
    }
    const ov = buildJobOverview(base, run as never)
    expect(ov.verdict).toBe("fail") // hard_gate 失败 → fail
    expect(ov.score).toBe(0.9)
    expect(ov.metrics).toEqual({ DR: 0.99, CPR: 0.95, condR: 0.9, avg_time_ms: 100 })
    expect(ov.summary).toEqual({ total: 2, passed: 1, failed: 1, skipped: 0 })
    expect(ov.dimension_pass).toEqual({ format: 1, commonsense: 1, soft: 1, preference: 1 })
    expect(ov.items[0]).toEqual({
      external_sample_id: "A",
      score: 0.1,
      passed: false,
      failures: [
        {
          name: "格式门禁",
          reason: "缺少 <html> 根标签",
          top_issues: ["缺 <html> 根标签"], // 从 details.dimensions[].issues 聚合 high
          files: ["index.html"], // 从 details.source_files 聚合（docs/arch/15 P3）
        },
      ],
    })
    expect(ov.items[1]!.failures).toEqual([])
  })

  it("verdict=pass when metrics meet thresholds and no hard_gate fail", () => {
    const run = {
      externalRunId: "r1",
      dr: 0.96,
      cpr: 0.91,
      condR: 0.85,
      avgReward: 0.82,
      avgTimeMs: 50,
      totalSamples: 1,
      thresholds: { DR: 0.95, CPR: 0.9, avg_reward: 0.8 },
      samples: [
        {
          id: "s1",
          externalSampleId: "A",
          status: "pass",
          reward: 0.82,
          sFormat: 1,
          sCommon: 1,
          sSoft: 0.7,
          sPref: 0.7,
          constraintResults: [],
        },
      ],
    }
    expect(buildJobOverview(base, run as never).verdict).toBe("pass")
  })

  it("verdict=fail when DR below threshold (阈值取自 run.thresholds)", () => {
    const run = {
      externalRunId: "r1",
      dr: 0.8,
      cpr: 0.95,
      condR: 0.9,
      avgReward: 0.9,
      avgTimeMs: 10,
      totalSamples: 1,
      thresholds: { DR: 0.95 },
      samples: [
        {
          id: "s1",
          externalSampleId: "A",
          status: "pass",
          reward: 0.9,
          sFormat: 1,
          sCommon: 1,
          sSoft: 0.9,
          sPref: 0.9,
          constraintResults: [],
        },
      ],
    }
    expect(buildJobOverview(base, run as never).verdict).toBe("fail")
  })

  it("dimension_pass 用默认阈值（format≥1 / commonsense>0 / soft≥0.6 / pref≥0.6）", () => {
    const run = {
      externalRunId: "r1",
      dr: 0.96,
      cpr: 0.91,
      condR: 0.85,
      avgReward: 0.82,
      avgTimeMs: 1,
      totalSamples: 1,
      thresholds: null,
      samples: [
        {
          id: "s1",
          externalSampleId: "A",
          status: "fail",
          reward: 0.3,
          sFormat: 1,
          sCommon: 0, // commonsense 未过
          sSoft: 0.4, // soft 未过
          sPref: 0.7,
          constraintResults: [{ name: "常识检查", reason: "图示错误", tier: "hard_score" }],
        },
      ],
    }
    const ov = buildJobOverview(base, run as never)
    // hard_score 非 hard_gate → 不强制 fail；指标达标 → pass
    expect(ov.verdict).toBe("pass")
    expect(ov.dimension_pass).toEqual({ format: 1, commonsense: 0, soft: 0, preference: 1 })
  })
})

describe("createEvalJobService.overview", () => {
  beforeEach(() => {
    mocks.findById.mockReset()
    mocks.runOverview.mockReset()
  })

  it("job 不存在 → null", async () => {
    mocks.findById.mockResolvedValue(null)
    expect(await createEvalJobService(tenant).overview("nope")).toBeNull()
  })

  it("job 未完成 → items 为空，且不查 run", async () => {
    mocks.findById.mockResolvedValue({
      id: "j1",
      runId: null,
      status: "running",
      webRunUrl: null,
      error: null,
    })
    const ov = await createEvalJobService(tenant).overview("j1")
    expect(ov!.items).toEqual([])
    expect(ov!.status).toBe("running")
    expect(mocks.runOverview).not.toHaveBeenCalled()
  })

  it("job failed → 回任务级 error + 空 items", async () => {
    mocks.findById.mockResolvedValue({
      id: "j1",
      runId: null,
      status: "failed",
      webRunUrl: null,
      error: { message: "boom", traceback: "..." },
    })
    const ov = await createEvalJobService(tenant).overview("j1")
    expect(ov!.status).toBe("failed")
    expect(ov!.error).toEqual({ message: "boom", traceback: "..." })
    expect(ov!.items).toEqual([])
  })

  it("job completed → 聚合 run（mock）", async () => {
    mocks.findById.mockResolvedValue({
      id: "j1",
      runId: "r1",
      status: "completed",
      webRunUrl: "http://x/run/r1",
      error: null,
    })
    mocks.runOverview.mockResolvedValue({
      externalRunId: "r1",
      dr: 0.96,
      cpr: 0.91,
      condR: 0.85,
      avgReward: 0.82,
      avgTimeMs: 50,
      totalSamples: 1,
      thresholds: null,
      samples: [
        {
          id: "s1",
          externalSampleId: "A",
          status: "pass",
          reward: 0.82,
          sFormat: 1,
          sCommon: 1,
          sSoft: 0.7,
          sPref: 0.7,
          constraintResults: [],
        },
      ],
    })
    const ov = await createEvalJobService(tenant).overview("j1")
    expect(ov!.verdict).toBe("pass")
    expect(ov!.items).toHaveLength(1)
    expect(mocks.runOverview).toHaveBeenCalledWith("p-1", "r1")
  })

  it("job completed 但 run 未找到 → 空 items（不阻塞调用方）", async () => {
    mocks.findById.mockResolvedValue({
      id: "j1",
      runId: "r1",
      status: "completed",
      webRunUrl: null,
      error: null,
    })
    mocks.runOverview.mockResolvedValue(null)
    const ov = await createEvalJobService(tenant).overview("j1")
    expect(ov!.items).toEqual([])
  })
})
