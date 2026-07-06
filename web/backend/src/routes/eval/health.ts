/**
 * eval 子系统健康检查（/api/v1/health）。
 */

import { Router } from "express"

const router = Router()

router.get("/", (_req, res) => {
  res.json({ status: "ok", subsystem: "eval" })
})

export default router
