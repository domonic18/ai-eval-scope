/**
 * 规则集目录路由（/api/v1/rule-sets）—— Phase 3 起动态化（对齐 12 §6.4）。
 *
 * 优先返回 DB 场景包资产（RuleSetAsset，经 catalog 导入/P3-4 发布），并合并构建期
 * 静态 catalog（rule-sets.json）的能力声明（capabilities/scopes）；DB 无数据时回退静态。
 * 第三方可据此发现场景包，并以 package_id（= rule_set_id 语义）提交评测。
 */

import { Router } from "express"
import { getPrisma } from "../../infra/prisma"
import { readRuleSetsCatalog } from "../../infra/ruleSetsCatalog"
import { pickLatestPerAsset } from "../../utils/versioning"

const router = Router()

interface StaticEntry {
  id: string
  name?: string
  description?: string
  capabilities?: string[]
  scopes?: string[]
  scenario_id?: string
  version?: string
}

router.get("/", async (_req, res) => {
  const staticCatalog = readRuleSetsCatalog() as StaticEntry[]
  const byId = new Map(staticCatalog.map((e) => [e.id, e]))

  // DB 场景包规则集（每个 assetId 取最新版本；与 catalog 共用 pickLatestPerAsset，避免
  // 字符串比较与数值 semver 不一致导致 1.10.0/1.9.0 分歧）
  const dbRows = await getPrisma().ruleSetAsset.findMany()
  const latest = pickLatestPerAsset(dbRows)

  const entries: StaticEntry[] = []
  const seen = new Set<string>()
  for (const r of latest) {
    const content = (r.content ?? {}) as Record<string, unknown>
    const base = byId.get(r.assetId)
    entries.push({
      id: r.assetId,
      name: (content.name as string) ?? base?.name ?? r.assetId,
      description: (content.description as string) ?? base?.description ?? "",
      capabilities: base?.capabilities ?? [],
      scopes: base?.scopes ?? ["single", "unit"],
      scenario_id: r.scenarioId,
      version: r.version,
    })
    seen.add(r.assetId)
  }
  // 静态 catalog 中未被 DB 覆盖的（如 format-only）保留
  for (const e of staticCatalog) {
    if (!seen.has(e.id)) entries.push(e)
  }

  res.json({ rule_sets: entries })
})

export default router
