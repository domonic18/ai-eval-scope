/**
 * 场景配置路由（/api/v1/scenarios）—— 纯只读目录视图（docs/plan/08 Web 纯可视化）。
 *
 * Web 仅做可视化展示：场景包的写入通道只有 importAssetsToDb 登记脚本（通道 A）
 * 与 auto-ingest 摄取（通道 B），本路由不再提供任何 POST 写端点
 * （发布/标签晋升/创建场景已随编辑器一并移除）。
 *
 * - GET  /                                  列出全部场景（公开）
 * - GET  /:id/catalog                       catalog（公开）
 * - GET  /:id/defaults                      默认指标定义 + 聚合策略
 * - GET  /:id/defaults/versions             默认配置版本历史
 * - GET  /:id/:kind/:assetId/content        资产完整内容（规则浏览器，只读）
 * - GET  /:id/:kind/:assetId/versions       资产版本历史（查看）
 * - GET  /:id/packages/:assetId             拉取场景包内容（executor/evaluator 运行时）
 */

import { Router } from "express"
import { PlatformError } from "../../middleware/errorHandler"
import { getPrisma } from "../../infra/prisma"
import { ScenarioRepository } from "../../repositories/scenario.repository"

const router = Router()
const repo = () => new ScenarioRepository()
const ASSET_KINDS = ["rule-sets", "prompts", "datasets", "task-sets", "sut-configs"] as const
type AssetKind = (typeof ASSET_KINDS)[number]

router.get("/", async (req, res) => {
  // ?source=official|auto_ingest：配置中心默认视角取 official（补缺注册场景不进默认视图）
  const source = typeof req.query.source === "string" && req.query.source ? req.query.source : undefined
  res.json({ scenarios: await repo().listScenarios(source) })
})

router.get("/:id/catalog", async (req, res) => {
  const catalog = await repo().getCatalog(req.params.id)
  if (!catalog) {
    res.status(404).json({ error: "scenario not found", scenario_id: req.params.id })
    return
  }
  res.json(catalog)
})

/** 场景默认指标定义 + 聚合策略（最新已发布版本；列表页 fetch，前端无 hardcode）。 */
router.get("/:id/defaults", async (req, res) => {
  const scenario = await getPrisma().scenario.findUnique({ where: { id: req.params.id }, select: { id: true } })
  if (!scenario) {
    res.status(404).json({ error: "scenario not found", scenario_id: req.params.id })
    return
  }
  const defaults = await repo().getDefaultsContent(req.params.id, req.query.version as string | undefined)
  const content = (defaults?.content ?? {}) as { metric_definitions?: unknown[]; aggregation_policy?: unknown }
  res.json({
    metric_definitions: content.metric_definitions ?? [],
    aggregation_policy: content.aggregation_policy ?? null,
  })
})

/** 场景默认配置版本历史（只读查看）。 */
router.get("/:id/defaults/versions", async (req, res) => {
  res.json({ versions: await repo().listDefaultsVersions(req.params.id) })
})

/** 资产完整内容（评测规则浏览器用，只读）。 */
router.get("/:id/:kind/:assetId/content", async (req, res, next) => {
  const kind = req.params.kind as AssetKind
  if (!ASSET_KINDS.includes(kind))
    return next(new PlatformError("unknown asset kind", { status: 404, code: "NOT_FOUND" }))
  const content = await repo().getAssetContent(req.params.id, kind, req.params.assetId, req.query.version as string | undefined)
  if (!content) {
    res.status(404).json({ error: "asset not found", asset_id: req.params.assetId })
    return
  }
  res.json({ content })
})

// 资产版本历史（只读查看）
router.get("/:id/:kind/:assetId/versions", async (req, res, next) => {
  const kind = req.params.kind as AssetKind
  if (!ASSET_KINDS.includes(kind)) return next(new PlatformError("unknown asset kind", { status: 404, code: "NOT_FOUND" }))
  res.json({ versions: await repo().listAssetVersions(req.params.id, kind, req.params.assetId) })
})

/**
 * 拉取场景包内容（S2-A，公开读，executor/evaluator 运行时获取最新版本）。
 * 解析：?version= > ?label=(如 production) > 最新。content 为 { manifest, files }。
 * 鉴权：与 GET /api/v1/rule-sets、catalog 一致，公开（场景包为非敏感配置）。
 */
router.get("/:id/packages/:assetId", async (req, res) => {
  const version = req.query.version as string | undefined
  const label = req.query.label as string | undefined
  const pkg = await repo().getPackageContent(req.params.id, req.params.assetId, version, label)
  if (!pkg) {
    res
      .status(404)
      .json({ error: "package not found", scenario_id: req.params.id, asset_id: req.params.assetId })
    return
  }
  res.json({
    package: {
      scenario_id: req.params.id,
      asset_id: req.params.assetId,
      version: pkg.version,
      labels: pkg.labels,
      content: pkg.content,
    },
  })
})

export default router
