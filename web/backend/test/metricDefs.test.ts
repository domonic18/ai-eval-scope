/**
 * resolveRunMetricDefs 纯函数单测（不依赖 DB / 不联网）。
 *
 * fixture 取自 edu 场景真实事故（run 20260918_081020）：包重构改名导致
 * 场景 defaults（edu:* 旧代）与 run 快照/指标键（kb:* 新代）两代并存，
 * 展示必须锚定 run 快照（docs/plan/08 不变量 3）。
 */

import { describe, it, expect } from "vitest"
import { resolveRunMetricDefs } from "../src/utils/metricDefs"

// 旧代定义（sasan-edu-safety 包，auto-ingest 于 2026-09-15）
const LEGACY_DEFAULTS = {
  metric_definitions: [
    { id: "edu:reward", name: "综合得分", threshold: 0.7 },
    { id: "edu:quality", name: "回答质量" },
  ],
}

// 新代定义（sasan-edu-kb-search 包，run 自带快照）
const CURRENT_SNAPSHOT = {
  metric_definitions: [
    { id: "kb:reward", name: "综合得分", threshold: 0.85 },
    { id: "kb:retrieval", name: "检索准确性", threshold: 0.85 },
  ],
}

describe("resolveRunMetricDefs（run 快照锚定）", () => {
  it("两代并存：run 快照优先，defaults 不参与（事故主场景）", () => {
    const r = resolveRunMetricDefs(CURRENT_SNAPSHOT, LEGACY_DEFAULTS)
    expect(r.source).toBe("run-snapshot")
    expect(r.defs.map((d) => d.id)).toEqual(["kb:reward", "kb:retrieval"])
  })

  it("快照缺失：回退场景 defaults（极老 run）", () => {
    const r = resolveRunMetricDefs(null, LEGACY_DEFAULTS)
    expect(r.source).toBe("scenario-defaults")
    expect(r.defs.map((d) => d.id)).toEqual(["edu:reward", "edu:quality"])
  })

  it("快照存在但无定义：回退 defaults", () => {
    const r = resolveRunMetricDefs({ snapshot_hash: "sha256:x" }, LEGACY_DEFAULTS)
    expect(r.source).toBe("scenario-defaults")
    expect(r.defs).toHaveLength(2)
  })

  it("双缺失：空 defs + source=none（调用方显式降级）", () => {
    expect(resolveRunMetricDefs(null, null)).toEqual({ defs: [], source: "none" })
  })

  it("非对象/非数组防御：不抛错，按缺失处理", () => {
    expect(resolveRunMetricDefs("garbage", 42)).toEqual({ defs: [], source: "none" })
    expect(resolveRunMetricDefs({ metric_definitions: "not-array" }, LEGACY_DEFAULTS).source).toBe(
      "scenario-defaults",
    )
  })

  it("兼容 camelCase 旧字段名 metricDefinitions", () => {
    const r = resolveRunMetricDefs({ metricDefinitions: [{ id: "a" }] }, null)
    expect(r.source).toBe("run-snapshot")
    expect(r.defs).toEqual([{ id: "a" }])
  })
})
