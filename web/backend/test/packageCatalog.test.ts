/**
 * packageCatalog 单测 — 纯函数，断言 package_ref 拼接与多版本/跨场景分组。
 */

import { describe, expect, it } from "vitest"
import {
  buildPackageRef,
  buildPackagesCatalog,
  type PackageCatalogRow,
} from "../src/infra/packageCatalog"

function row(over: Partial<PackageCatalogRow> & Pick<PackageCatalogRow, "scenarioId" | "assetId">): PackageCatalogRow {
  return {
    version: "1.0.0",
    labels: ["production", "latest"],
    content: { manifest: { id: over.assetId, scenario: over.scenarioId } },
    ...over,
  }
}

describe("buildPackageRef", () => {
  it("uses :latest tag when label present", () => {
    expect(buildPackageRef("courseware", "courseware", "1.0.0", ["production", "latest"])).toBe(
      "courseware/courseware:latest",
    )
  })

  it("falls back to :production when no latest", () => {
    expect(buildPackageRef("code", "code", "2.0.0", ["production"])).toBe("code/code:production")
  })

  it("falls back to exact version when no reserved label", () => {
    expect(buildPackageRef("courseware", "courseware", "1.0.0", [])).toBe("courseware/courseware:1.0.0")
  })
})

describe("buildPackagesCatalog", () => {
  it("emits package_ref and surfaces manifest fields", () => {
    const rows = [
      row({
        scenarioId: "courseware",
        assetId: "courseware",
        content: {
          manifest: {
            id: "courseware",
            scenario: "courseware",
            name: "课件质量评估内置包",
            description: "desc",
            artifact_types: ["courseware/*"],
          },
        },
      }),
    ]
    const [e] = buildPackagesCatalog(rows)
    expect(e.package_ref).toBe("courseware/courseware:latest")
    expect(e.package_id).toBe("courseware")
    expect(e.scenario).toBe("courseware")
    expect(e.name).toBe("课件质量评估内置包")
    expect(e.artifact_types).toEqual(["courseware/*"])
  })

  it("picks the newest version per (scenario, asset) on tied rank (semver wins)", () => {
    // 同 rank（都带 latest）→ 数值 semver 高者胜（与 pickLatestPerAsset 一致）
    const rows = [
      row({ scenarioId: "courseware", assetId: "courseware", version: "1.0.0", labels: ["latest"] }),
      row({ scenarioId: "courseware", assetId: "courseware", version: "1.2.0", labels: ["latest"] }),
    ]
    const entries = buildPackagesCatalog(rows)
    expect(entries).toHaveLength(1)
    expect(entries[0].version).toBe("1.2.0")
    expect(entries[0].package_ref).toBe("courseware/courseware:latest")
  })

  it("production rank beats latest when on different versions", () => {
    // 旧版本挂 production(rank 3)、新版本仅 latest(rank 1) → production 行视为"最新"
    const rows = [
      row({ scenarioId: "courseware", assetId: "courseware", version: "1.0.0", labels: ["production"] }),
      row({ scenarioId: "courseware", assetId: "courseware", version: "1.2.0", labels: ["latest"] }),
    ]
    const entries = buildPackagesCatalog(rows)
    expect(entries[0].version).toBe("1.0.0")
  })

  it("does not merge same-named assets across different scenarios", () => {
    // 两个场景都有 assetId 同名（如 "quality"），不应合并
    const rows = [
      row({ scenarioId: "courseware", assetId: "quality" }),
      row({ scenarioId: "code", assetId: "quality" }),
    ]
    const entries = buildPackagesCatalog(rows)
    expect(entries).toHaveLength(2)
    expect(new Set(entries.map((e) => e.scenario))).toEqual(new Set(["courseware", "code"]))
  })

  it("falls back to assetId when manifest.id missing", () => {
    const rows = [
      row({
        scenarioId: "courseware",
        assetId: "courseware",
        content: { manifest: { scenario: "courseware" } }, // 无 id
      }),
    ]
    const [e] = buildPackagesCatalog(rows)
    expect(e.package_id).toBe("courseware")
    expect(e.package_ref).toBe("courseware/courseware:latest")
  })

  it("returns empty array for no rows", () => {
    expect(buildPackagesCatalog([])).toEqual([])
  })
})
