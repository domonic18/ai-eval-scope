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

/** 更新场景默认指标定义 / 聚合策略（admin；直接覆盖 JSONB，非版本化）。 */
router.patch("/:id/defaults", requireAuth, platformAdminGuard, async (req, res, next) => {
  const { metric_definitions, aggregation_policy } = req.body ?? {}
  if (metric_definitions === undefined && aggregation_policy === undefined) {
    return next(
      new PlatformError("至少提供 metric_definitions 或 aggregation_policy", {
        status: 400,
        code: "VALIDATION_ERROR",
      }),
    )
  }
  if (metric_definitions !== undefined && !Array.isArray(metric_definitions)) {
    return next(new PlatformError("metric_definitions 必须为数组", { status: 400, code: "VALIDATION_ERROR" }))
  }
  if (
    aggregation_policy !== undefined &&
    (typeof aggregation_policy !== "object" || Array.isArray(aggregation_policy))
  ) {
    return next(new PlatformError("aggregation_policy 必须为对象", { status: 400, code: "VALIDATION_ERROR" }))
  }
  try {
    await repo().updateDefaults(req.params.id, {
      metricDefinitions: metric_definitions,
      aggregationPolicy: aggregation_policy,
    })
    res.json({ ok: true })
  } catch (e) {
    next(e)
  }
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
