/**
 * 规则集目录路由（/api/v1/rule-sets）—— 托管构建期生成的静态 catalog。
 *
 * catalog 由 scripts/gen_rule_sets.py 在评估器环境下调用 CapabilityResolver 生成，
 * 落 web/backend/assets/rule-sets.json 并提交入库（docs/arch/14 §6.3）。
 */

import { Router } from "express"
import { readRuleSetsCatalog } from "../../infra/ruleSetsCatalog"

const router = Router()

router.get("/", (_req, res) => {
  res.json({ rule_sets: readRuleSetsCatalog() })
})

export default router
