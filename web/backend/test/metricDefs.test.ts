/**
 * metricDefs 纯函数单测（不依赖 DB / 不联网）。
 *
 * fixture 取自 edu 场景真实事故（run 20260918_081020）：包重构改名导致
 * 场景 defaults（edu:* 旧代）与 run 快照/指标键（kb:* 新代）两代并存，
 * 展示必须锚定 run 快照（docs/plan/08 不变量 3）。
 *
 * 批次 C：resolveRunDefinitions（血缘 meta）+ pairRunDefs（列表行级配对）。
 */

import { describe, it, expect, vi } from "vitest"
import {
  resolveRunMetricDefs,
  resolveRunDefinitions,
  pairRunDefs,
  type DefsSource,
  type PairableRunRow,
} from "../src/utils/metricDefs"

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

describe("resolveRunDefinitions（血缘 meta，批次 C）", () => {
  it("快照命中：source/snapshotHash 来自快照，defaultsHash 来自兜底入参", () => {
    const r = resolveRunDefinitions(
      { content: CURRENT_SNAPSHOT, contentHash: "sha256:snap1" },
      { content: LEGACY_DEFAULTS, contentHash: "sha256:def1" },
    )
    expect(r.source).toBe("run-snapshot")
    expect(r.snapshotHash).toBe("sha256:snap1")
    expect(r.defaultsHash).toBe("sha256:def1")
    expect(r.defs.map((d) => d.id)).toEqual(["kb:reward", "kb:retrieval"])
  })

  it("无快照：snapshotHash=null，defaultsHash 仍回传（兜底血缘可核查）", () => {
    const r = resolveRunDefinitions(null, { content: LEGACY_DEFAULTS, contentHash: "sha256:def1" })
    expect(r.source).toBe("scenario-defaults")
    expect(r.snapshotHash).toBeNull()
    expect(r.defaultsHash).toBe("sha256:def1")
  })

  it("双缺失：全 meta 为 null/none（不臆造）", () => {
    const r = resolveRunDefinitions({ content: {}, contentHash: null }, null)
    expect(r.source).toBe("none")
    expect(r.defs).toEqual([])
    expect(r.snapshotHash).toBeNull()
    expect(r.defaultsHash).toBeNull()
  })
})

describe("pairRunDefs（列表行级配对，批次 C）", () => {
  const snapA = { content: CURRENT_SNAPSHOT, contentHash: "sha256:snapA" }
  const snapB = {
    content: { metric_definitions: [{ id: "edu:reward", threshold: 0.7 }] },
    contentHash: "sha256:snapB",
  }
  const defaultsFor = async (scn: string): Promise<DefsSource | null> =>
    scn === "scn-old" ? { content: LEGACY_DEFAULTS, contentHash: "sha256:defOld" } : null

  it("每行 defs 锚定各自快照，重 content 剥离不下发", async () => {
    const rows: PairableRunRow[] = [
      { scenarioId: "scn-new", runConfigSnapshot: { ...snapA } },
      { scenarioId: "scn-old", runConfigSnapshot: { ...snapB } },
    ]
    const getDefaults = vi.fn(defaultsFor)
    await pairRunDefs(rows, getDefaults)
    expect(rows[0].metricDefinitions?.map((d) => d.id)).toEqual(["kb:reward", "kb:retrieval"])
    expect(rows[1].metricDefinitions?.map((d) => d.id)).toEqual(["edu:reward"])
    expect("runConfigSnapshot" in rows[0]).toBe(false)
    expect("runConfigSnapshot" in rows[1]).toBe(false)
  })

  it("同 hash 只解析一次（memo），defaults 每场景至多取一次", async () => {
    const rows: PairableRunRow[] = [
      { scenarioId: "scn-new", runConfigSnapshot: { ...snapA } },
      { scenarioId: "scn-new", runConfigSnapshot: { ...snapA, contentHash: "sha256:snapA" } },
      { scenarioId: "scn-old", runConfigSnapshot: null },
    ]
    const getDefaults = vi.fn(defaultsFor)
    await pairRunDefs(rows, getDefaults)
    // 每场景至多取一次（scn-new 快照行兜底需要 + scn-old 无快照兜底）；同 hash 两行不重复解析
    expect(getDefaults).toHaveBeenCalledTimes(2)
    expect(getDefaults).toHaveBeenNthCalledWith(1, "scn-new")
    expect(getDefaults).toHaveBeenNthCalledWith(2, "scn-old")
    expect(rows[0].metricDefinitions).toEqual(rows[1].metricDefinitions)
    expect(rows[2].metricDefinitions?.[0].id).toBe("edu:reward") // defaults 兜底
  })

  it("无快照且场景无 defaults：空 defs，不抛错（source=none 显式降级由调用方判断）", async () => {
    const rows: PairableRunRow[] = [{ scenarioId: "scn-unknown", runConfigSnapshot: null }]
    await pairRunDefs(rows, defaultsFor)
    expect(rows[0].metricDefinitions).toEqual([])
  })

  it("getDefaults 抛错按无 defaults 处理（不让单场景故障拖垮列表）", async () => {
    const rows: PairableRunRow[] = [{ scenarioId: "scn-boom", runConfigSnapshot: null }]
    await pairRunDefs(rows, async () => {
      throw new Error("db down")
    })
    expect(rows[0].metricDefinitions).toEqual([])
  })
})
