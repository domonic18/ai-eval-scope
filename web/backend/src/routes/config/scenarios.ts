/**
 * 场景配置路由（/api/v1/scenarios）—— Phase 3 动态 catalog + 包发布（对齐 13 §11.2、09 §9.5）。
 *
 * - GET  /                列出全部场景（公开）
 * - GET  /:id/catalog     返回该场景下规则集/提示词/数据集 catalog（公开，替代静态 rule-sets.json）
 * - POST /:id/packages    发布/更新一个场景包版本（platform admin）
 */

import { Router } from "express"
import { requireAuth } from "../../middleware/auth"
import { platformAdminGuard } from "../../middleware/adminGuard"
import { PlatformError } from "../../middleware/errorHandler"
import { ScenarioRepository } from "../../repositories/scenario.repository"

const router = Router()
const repo = () => new ScenarioRepository()

router.get("/", async (_req, res) => {
  res.json({ scenarios: await repo().listScenarios() })
})

router.get("/:id/catalog", async (req, res) => {
  const catalog = await repo().getCatalog(req.params.id)
  if (!catalog) {
    res.status(404).json({ error: "scenario not found", scenario_id: req.params.id })
    return
  }
  res.json(catalog)
})

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
