/**
 * overview 速览单测（docs/arch/12 §6.6）：
 *  - buildJobOverview 纯函数：verdict / summary / dimension_pass / items / failures
 *  - createEvalJobService.overview：mock 仓储，覆盖 未完成→空 items / completed→聚合 / run 缺失
 *
 *  数据格式：Phase 5 场景化指标 JSONB（run.metrics / sample.metrics），键为 MetricDefinition.id。
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
      metrics: {
        "courseware:document_rate": 0.99,
        "courseware:constraint_pass_rate": 0.95,
        "courseware:conditional_reward": 0.9,
        "courseware:reward": 0.9,
        "courseware:avg_time_ms": 100,
      },
      totalSamples: 2,
      thresholds: null,
      samples: [
        {
          id: "s1",
          externalSampleId: "A",
          status: "fail",
          reward: 0.1,
          sFormat: null,
          sCommon: null,
          sSoft: null,
          sPref: null,
          metrics: { "courseware:s_format": -3, "courseware:s_common": 0, "courseware:s_soft": 0.5, "courseware:s_pref": 0.4 },
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
          sFormat: null,
          sCommon: null,
          sSoft: null,
          sPref: null,
          metrics: { "courseware:s_format": 1, "courseware:s_common": 1, "courseware:s_soft": 0.9, "courseware:s_pref": 0.8 },
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
          top_issues: ["缺 <html> 根标签"],
          files: ["index.html"],
        },
      ],
    })
    expect(ov.items[1]!.failures).toEqual([])
  })

  it("verdict=pass when metrics meet thresholds and no hard_gate fail", () => {
    const run = {
      externalRunId: "r1",
      metrics: {
        "courseware:document_rate": 0.96,
        "courseware:constraint_pass_rate": 0.91,
        "courseware:conditional_reward": 0.85,
        "courseware:reward": 0.82,
        "courseware:avg_time_ms": 50,
      },
      totalSamples: 1,
      thresholds: { DR: 0.95, CPR: 0.9, avg_reward: 0.8 },
      samples: [
        {
          id: "s1",
          externalSampleId: "X",
          status: "pass",
          reward: 0.82,
          sFormat: null,
          sCommon: null,
          sSoft: null,
          sPref: null,
          metrics: { "courseware:s_format": 1, "courseware:s_common": 1, "courseware:s_soft": 0.85, "courseware:s_pref": 0.8 },
          constraintResults: [],
        },
      ],
    }
    const ov = buildJobOverview(base, run as never)
    expect(ov.verdict).toBe("pass")
    expect(ov.score).toBe(0.82)
  })

  it("dimension_pass 用默认阈值（format≥1 / commonsense>0 / soft≥0.6 / pref≥0.6）", () => {
    const run = {
      externalRunId: "r1",
      metrics: { "courseware:document_rate": 1, "courseware:constraint_pass_rate": 1, "courseware:reward": 0.9 },
      totalSamples: 3,
      thresholds: null,
      samples: [
        {
          id: "s1", externalSampleId: "A", status: "pass", reward: 0.9,
          sFormat: null, sCommon: null, sSoft: null, sPref: null,
          metrics: { "courseware:s_format": 1, "courseware:s_common": 1, "courseware:s_soft": 0.7, "courseware:s_pref": 0.65 },
          constraintResults: [],
        },
        {
          id: "s2", externalSampleId: "B", status: "pass", reward: 0.6,
          sFormat: null, sCommon: null, sSoft: null, sPref: null,
          metrics: { "courseware:s_format": 1, "courseware:s_common": 0, "courseware:s_soft": 0.4, "courseware:s_pref": 0.3 },
          constraintResults: [],
        },
        {
          id: "s3", externalSampleId: "C", status: "fail", reward: 0,
          sFormat: null, sCommon: null, sSoft: null, sPref: null,
          metrics: { "courseware:s_format": -3, "courseware:s_common": 0, "courseware:s_soft": 0, "courseware:s_pref": 0 },
          constraintResults: [{ name: "格式", reason: "r", tier: "hard_score", details: {} }],
        },
      ],
    }
    const ov = buildJobOverview(base, run as never)
    expect(ov.dimension_pass).toEqual({ format: 2, commonsense: 1, soft: 1, preference: 1 })
  })
})

describe("createEvalJobService.overview", () => {
  beforeEach(() => {
    mocks.findById.mockReset()
    mocks.runOverview.mockReset()
  })

  it("job 未完成 → 空 items", async () => {
    mocks.findById.mockResolvedValue({ id: "j1", status: "running", runId: null, webRunUrl: null, error: null })
    const svc = createEvalJobService(tenant)
    const ov = await svc.overview("j1")
    expect(ov.items).toEqual([])
  })

  it("job completed → 聚合 run（mock）", async () => {
    mocks.findById.mockResolvedValue({ id: "j1", status: "completed", runId: "r1", webRunUrl: "http://x", error: null })
    mocks.runOverview.mockResolvedValue({
      externalRunId: "r1",
      metrics: { "courseware:document_rate": 0.96, "courseware:constraint_pass_rate": 0.91, "courseware:reward": 0.82 },
      totalSamples: 1,
      thresholds: null,
      samples: [
        {
          id: "s1", externalSampleId: "A", status: "pass", reward: 0.82,
          sFormat: null, sCommon: null, sSoft: null, sPref: null,
          metrics: { "courseware:s_format": 1, "courseware:s_common": 1, "courseware:s_soft": 0.85, "courseware:s_pref": 0.8 },
          constraintResults: [],
        },
      ],
    })
    const svc = createEvalJobService(tenant)
    const ov = await svc.overview("j1")
    expect(ov.verdict).toBe("pass")
    expect(ov.items).toHaveLength(1)
  })

  it("job completed but run 未找到 → 空 items", async () => {
    mocks.findById.mockResolvedValue({ id: "j1", status: "completed", runId: "r1", webRunUrl: null, error: null })
    mocks.runOverview.mockResolvedValue(null)
    const svc = createEvalJobService(tenant)
    const ov = await svc.overview("j1")
    expect(ov.items).toEqual([])
  })
})
