/**
 * 场景包版本/标签解析工具（S1-3 统一）。
 *
 * 历史上 catalog（`scenario.repository._latestPerAsset`）用数值 semver，而规则集发现端
 * （`routes/eval/ruleSets`）用字符串比较，导致 `1.10.0` 与 `1.9.0` 两端返回不同版本。
 * 本模块抽出唯一的解析逻辑，两端共用。
 */

/** 数值 semver 比较（最多 3 段，缺省补 0；非数字段按 0 处理）。返回 <0 / 0 / >0。 */
export function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map((n) => parseInt(n, 10) || 0)
  const pb = b.split(".").map((n) => parseInt(n, 10) || 0)
  for (let i = 0; i < 3; i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0)
    if (d !== 0) return d
  }
  return 0
}

/** 互斥标签：同一资产内每个标签全局唯一（S1-4，晋升时从其它版本摘除）。 */
export const MUTUALLY_EXCLUSIVE_LABELS = ["production", "staging", "latest"] as const

const LABEL_PRIORITY: Readonly<Record<string, number>> = {
  production: 3,
  staging: 2,
  latest: 1,
}

/** 标签 rank：production > staging > latest > 无标签。 */
export function labelRank(labels: string[]): number {
  for (const [lbl, rank] of Object.entries(LABEL_PRIORITY)) {
    if (labels.includes(lbl)) return rank
  }
  return 0
}

/** `b` 是否比 `a` 更「新」（应作为最新版本选中）：rank 高者优先；并列取数值版本号高者。 */
export function isNewer(
  a: { labels: string[]; version: string },
  b: { labels: string[]; version: string },
): boolean {
  const ra = labelRank(a.labels)
  const rb = labelRank(b.labels)
  if (rb !== ra) return rb > ra
  return compareVersions(b.version, a.version) > 0
}

/**
 * 每个 assetId 取「最新」一条（rank 高者优先，并列取数值 semver 高者）。
 * catalog 与 rule-sets 发现端共用，保证两端一致。
 */
export function pickLatestPerAsset<T extends { assetId: string; version: string; labels: string[] }>(
  rows: T[],
): T[] {
  const byAsset = new Map<string, T>()
  for (const r of rows) {
    const prev = byAsset.get(r.assetId)
    if (!prev || isNewer(prev, r)) byAsset.set(r.assetId, r)
  }
  return [...byAsset.values()]
}
