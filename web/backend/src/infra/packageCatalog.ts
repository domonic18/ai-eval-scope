/**
 * 场景包目录组装（MCP list_packages / 第三方发现用）。
 *
 * 从 ScenarioPackage 行（DB 权威源）组装出可直接抄进 submit_eval_job.package_ref
 * 的引用串，补齐 rule-sets 发现端"只给 scenario_id/version、不给 package_id"的缺口
 * （第三方/Agent 无法据此拼出 executor 能解析的 scenario/package[:version_or_label]）。
 *
 * 纯函数：不触 DB、不耦合 Prisma 类型（入参用结构化 Row 类型），便于单测。
 */

import { isNewer } from "../utils/versioning"

/** buildPackagesCatalog 的输入行（结构对齐 Prisma ScenarioPackage 投影）。 */
export interface PackageCatalogRow {
  scenarioId: string
  assetId: string
  version: string
  labels: string[]
  /** 发布结构 { manifest, files }；manifest = agent_eval.yaml 的 package 段。 */
  content: unknown
}

export interface PackageCatalogEntry {
  /** 可直接用于 submit_eval_job.package_ref：scenario/package_id:latest（或精确版本）。 */
  package_ref: string
  scenario: string
  package_id: string
  version: string
  labels: string[]
  name: string | null
  description: string | null
  artifact_types: string[]
}

interface ManifestShape {
  id?: unknown
  scenario?: unknown
  name?: unknown
  description?: unknown
  artifact_types?: unknown
}

/**
 * 由 manifest + 行字段拼 package_ref 的版本指针。
 *
 * - labels 含 latest/production → 用该标签（latest 优先，符合"短形式 + 标签"约定，
 *   且导入/发布逻辑保证 latest 存在）；
 * - 否则回退精确版本，保证 ref 一定可解析。
 */
export function buildPackageRef(
  scenario: string,
  packageId: string,
  version: string,
  labels: string[],
): string {
  const tag = labels.includes("latest")
    ? "latest"
    : labels.includes("production")
      ? "production"
      : null
  return tag ? `${scenario}/${packageId}:${tag}` : `${scenario}/${packageId}:${version}`
}

/**
 * 组装场景包目录：按 (scenarioId, assetId) 取最新版本（rank + 数值 semver，与
 * pickLatestPerAsset 同策略；此处按 composite key 分组，避免跨 scenario 同名 assetId 合并）。
 *
 * package_id 取 manifest.id（executor resolve_ref 解析的就是 manifest.scenario/id），
 * manifest 缺失时兜底 assetId（导入侧 assetId == manifest.id）。
 */
export function buildPackagesCatalog(rows: PackageCatalogRow[]): PackageCatalogEntry[] {
  // composite key 分组取最新
  const latest = new Map<string, PackageCatalogRow>()
  for (const r of rows) {
    const key = `${r.scenarioId}/${r.assetId}`
    const prev = latest.get(key)
    if (!prev || isNewer(prev, r)) latest.set(key, r)
  }

  const entries: PackageCatalogEntry[] = []
  for (const r of latest.values()) {
    const manifest = ((r.content as { manifest?: ManifestShape } | null)?.manifest ?? {}) as ManifestShape
    const packageId =
      typeof manifest.id === "string" && manifest.id ? manifest.id : r.assetId
    const scenario = r.scenarioId
    const artifactTypes = Array.isArray(manifest.artifact_types)
      ? manifest.artifact_types.map((x) => String(x))
      : []
    entries.push({
      package_ref: buildPackageRef(scenario, packageId, r.version, r.labels),
      scenario,
      package_id: packageId,
      version: r.version,
      labels: r.labels,
      name: typeof manifest.name === "string" ? manifest.name : null,
      description: typeof manifest.description === "string" ? manifest.description : null,
      artifact_types: artifactTypes,
    })
  }
  // 稳定排序：scenario → package_id，便于展示与断言
  entries.sort((a, b) =>
    a.scenario === b.scenario
      ? a.package_id.localeCompare(b.package_id)
      : a.scenario.localeCompare(b.scenario),
  )
  return entries
}
