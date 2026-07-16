/**
 * 场景配置路由（/api/v1/scenarios）—— Phase 3 catalog + Phase 4 asset 编辑/发布。
 *
 * - GET  /                                  列出全部场景（公开）
 * - GET  /:id/catalog                       catalog（公开）
 * - POST /:id/packages                      发布场景包版本（admin）
 * - POST /:id/rule-sets                     发布规则集资产版本（admin）         [P4-2]
 * - POST /:id/prompts                       发布提示词资产版本（admin）         [P4-3]
 * - POST /:id/datasets                      发布数据集资产版本（admin）         [P4-4]
 * - GET  /:id/:kind/:assetId/versions       资产版本历史（VersionTimeline）     [P4-5]
 * - POST /:id/:kind/:assetId/versions/:ver/labels  标签晋升（admin）            [P4-5]
 */

import { Router } from "express"
import { requireAuth } from "../../middleware/auth"
import { platformAdminGuard } from "../../middleware/adminGuard"
import { PlatformError } from "../../middleware/errorHandler"
import { getPrisma } from "../../infra/prisma"
import { ScenarioRepository } from "../../repositories/scenario.repository"

const router = Router()
const repo = () => new ScenarioRepository()
const ASSET_KINDS = ["rule-sets", "prompts", "datasets"] as const
type AssetKind = (typeof ASSET_KINDS)[number]

router.get("/", async (_req, res) => {
  res.json({ scenarios: await repo().listScenarios() })
})

/** 创建场景（admin）。 */
router.post("/", requireAuth, platformAdminGuard, async (req, res, next) => {
  const { id, name, description } = req.body ?? {}
  if (!id || !name) {
    return next(new PlatformError("id 与 name 必填", { status: 400, code: "VALIDATION_ERROR" }))
  }
  try {
    const r = await getPrisma()
    const existing = await r.scenario.findUnique({ where: { id } })
    if (existing) {
      return next(new PlatformError(`场景已存在: ${id}`, { status: 409, code: "CONFLICT" }))
    }
    await r.scenario.create({ data: { id, name, description: description ?? null } })
    res.status(201).json({ scenario: { id, name, description: description ?? null } })
  } catch (e) {
    next(e)
  }
})

router.get("/:id/catalog", async (req, res) => {
  const catalog = await repo().getCatalog(req.params.id)
  if (!catalog) {
    res.status(404).json({ error: "scenario not found", scenario_id: req.params.id })
    return
  }
  res.json(catalog)
})

/** 场景默认指标定义 + 聚合策略（列表页 fetch，前端无 hardcode）。 */
router.get("/:id/defaults", async (req, res) => {
  const scenario = await getPrisma().scenario.findUnique({
    where: { id: req.params.id },
    select: { defaultMetricDefinitions: true, defaultAggregationPolicy: true },
  })
  if (!scenario) {
    res.status(404).json({ error: "scenario not found", scenario_id: req.params.id })
    return
  }
  res.json({
    metric_definitions: scenario.defaultMetricDefinitions ?? [],
    aggregation_policy: scenario.defaultAggregationPolicy ?? null,
  })
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

async function publishAssetHandler(
  kind: AssetKind,
  scenarioId: string,
  body: Record<string, unknown>,
  createdBy: string,
): Promise<unknown> {
  const r = repo()
  const common = {
    assetId: body.asset_id as string,
    version: body.version as string,
    labels: (body.labels as string[]) ?? [],
    content: (body.content as Record<string, unknown>) ?? {},
    createdBy,
    packageId: body.package_id as string | undefined,
  }
  if (!common.assetId || !common.version) {
    throw new PlatformError("asset_id 与 version 必填", { status: 400, code: "VALIDATION_ERROR" })
  }
  if (kind === "rule-sets") return r.publishRuleSetAsset(scenarioId, common)
  if (kind === "prompts")
    return r.publishPromptAsset(scenarioId, { ...common, namespace: body.namespace as string | undefined })
  const role = (body.role as string) ?? "reference"
  if (role !== "test" && role !== "reference") {
    throw new PlatformError("role 必须为 test 或 reference", { status: 400, code: "VALIDATION_ERROR" })
  }
  return r.publishDatasetAsset(scenarioId, {
    ...common,
    role,
    backendType: (body.backend_type as string) ?? "yaml_file",
    backendConfig: (body.backend_config as Record<string, unknown>) ?? {},
  })
}

for (const kind of ASSET_KINDS) {
  router.post(`/:id/${kind}`, requireAuth, platformAdminGuard, async (req, res, next) => {
    try {
      const result = await publishAssetHandler(kind, req.params.id, req.body ?? {}, req.user!.userId)
      res.status(201).json({ asset: result })
    } catch (e) {
      next(e)
    }
  })
}

// 资产版本历史（VersionTimeline）
router.get("/:id/:kind/:assetId/versions", async (req, res, next) => {
  const kind = req.params.kind as AssetKind
  if (!ASSET_KINDS.includes(kind)) return next(new PlatformError("unknown asset kind", { status: 404, code: "NOT_FOUND" }))
  res.json({ versions: await repo().listAssetVersions(req.params.id, kind, req.params.assetId) })
})

// 标签晋升（覆盖某版本 labels）
router.post(
  "/:id/:kind/:assetId/versions/:ver/labels",
  requireAuth,
  platformAdminGuard,
  async (req, res, next) => {
    const kind = req.params.kind as AssetKind
    if (!ASSET_KINDS.includes(kind)) return next(new PlatformError("unknown asset kind", { status: 404, code: "NOT_FOUND" }))
    try {
      await repo().setAssetLabels(req.params.id, kind, req.params.assetId, req.params.ver, (req.body.labels as string[]) ?? [])
      res.json({ ok: true })
    } catch (e) {
      next(e)
    }
  },
)

router.post(
  "/:id/packages",
  requireAuth,
  platformAdminGuard,
  async (req, res, next) => {
    const body = req.body ?? {}
    if (!body.asset_id || !body.version) {
      return next(
        new PlatformError("asset_id 与 version 必填", { status: 400, code: "VALIDATION_ERROR" }),
      )
    }
    try {
      const result = await repo().publishPackage(req.params.id, {
        assetId: body.asset_id,
        version: body.version,
        labels: body.labels ?? [],
        name: body.name,
        description: body.description,
        content: body.content ?? {},
        createdBy: req.user!.userId,
      })
      res.status(201).json({ package: result })
    } catch (e) {
      next(e)
    }
  },
)

export default router
