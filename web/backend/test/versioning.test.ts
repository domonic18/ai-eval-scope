/**
 * versioning 纯单元测试（S1-3）—— 不依赖 DB。
 * 验证数值 semver、标签 rank、pickLatestPerAsset 的统一解析（修掉字符串比较 bug）。
 */

import { describe, it, expect } from "vitest"
import {
  compareVersions,
  labelRank,
  isNewer,
  pickLatestPerAsset,
  MUTUALLY_EXCLUSIVE_LABELS,
} from "../src/utils/versioning"

describe("compareVersions", () => {
  it("按数值 semver 比较（非字符串）", () => {
    expect(compareVersions("1.9.0", "1.10.0")).toBeLessThan(0) // 字符串比较会判反
    expect(compareVersions("1.10.0", "1.9.0")).toBeGreaterThan(0)
    expect(compareVersions("1.0.0", "1.0.0")).toBe(0)
    expect(compareVersions("2.0.0", "1.99.99")).toBeGreaterThan(0)
  })

  it("缺省段补 0", () => {
    expect(compareVersions("1.0", "1.0.0")).toBe(0)
    expect(compareVersions("1", "1.0.2")).toBeLessThan(0)
  })

  it("非数字段按 0", () => {
    expect(compareVersions("1.x.0", "1.0.0")).toBe(0)
  })
})

describe("labelRank", () => {
  it("production > staging > latest > 无", () => {
    expect(labelRank(["production"])).toBeGreaterThan(labelRank(["staging"]))
    expect(labelRank(["staging"])).toBeGreaterThan(labelRank(["latest"]))
    expect(labelRank(["latest"])).toBeGreaterThan(labelRank([]))
    expect(labelRank(["foo"])).toBe(0)
  })
})

describe("isNewer", () => {
  it("rank 高者优先于版本号", () => {
    expect(isNewer({ labels: [], version: "2.0.0" }, { labels: ["production"], version: "1.0.0" })).toBe(true)
  })

  it("rank 相同时取数值版本号高者（1.10.0 > 1.9.0）", () => {
    expect(isNewer({ labels: [], version: "1.9.0" }, { labels: [], version: "1.10.0" })).toBe(true)
    expect(isNewer({ labels: [], version: "1.10.0" }, { labels: [], version: "1.9.0" })).toBe(false)
  })
})

describe("pickLatestPerAsset", () => {
  const mk = (assetId: string, version: string, labels: string[] = []) => ({
    assetId,
    version,
    labels,
  })

  it("每个 asset 取一条，1.10.0 胜过 1.9.0（无标签）", () => {
    const out = pickLatestPerAsset([
      mk("a", "1.9.0"),
      mk("a", "1.10.0"),
      mk("a", "1.8.0"),
    ])
    expect(out).toHaveLength(1)
    expect(out[0].version).toBe("1.10.0")
  })

  it("production 标签胜过更高版本号", () => {
    const out = pickLatestPerAsset([mk("a", "2.0.0"), mk("a", "1.0.0", ["production"])])
    expect(out[0].version).toBe("1.0.0")
  })

  it("多资产各取一条", () => {
    const out = pickLatestPerAsset([
      mk("a", "1.0.0", ["latest"]),
      mk("b", "2.0.0"),
      mk("b", "1.5.0", ["staging"]),
    ])
    const byId = new Map(out.map((r) => [r.assetId, r.version]))
    expect(byId.get("a")).toBe("1.0.0")
    expect(byId.get("b")).toBe("1.5.0") // staging 胜过 2.0.0
  })
})

describe("MUTUALLY_EXCLUSIVE_LABELS", () => {
  it("含 production / staging / latest", () => {
    expect([...MUTUALLY_EXCLUSIVE_LABELS]).toEqual(["production", "staging", "latest"])
  })
})
