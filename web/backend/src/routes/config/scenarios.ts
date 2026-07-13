/**
 * 场景配置路由（/api/v1/scenarios）—— Phase 3 动态 catalog（对齐 13 §11.2、09 §9.5）。
 *
 * - GET /                列出全部场景
 * - GET /:id/catalog     返回该场景下规则集/提示词/数据集 catalog（替代静态 rule-sets.json）
 *
 * 读公开（与 /api/v1/rule-sets 一致，供前端 DebugPage 与第三方拉取）。
 */

import { Router } from "express"
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

export default router
