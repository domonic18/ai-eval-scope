/**
 * 制品路由（/api/v1/artifacts）。
 *  - GET /:id       校验归属后 302 重定向到 presigned GET（下载用）
 *  - GET /:id/preview  返回 presigned URL + 元信息（JSON，前端 iframe/fetch 用）
 */

import { Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { artifactGuard } from "../middleware/tenantGuard"
import { createQueryService } from "../services/query.service"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

router.get(
  "/:id",
  requireAuth,
  artifactGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!)
    const dl = await svc.artifactDownload(req.params.id)
    res.redirect(302, dl.url)
  }),
)

router.get(
  "/:id/preview",
  requireAuth,
  artifactGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!)
    const dl = await svc.artifactDownload(req.params.id)
    // 返回 presigned URL（短时效，前端 iframe/fetch 直接用，无需再带 JWT）
    res.json({ url: dl.url, contentType: dl.contentType, filename: dl.filename })
  }),
)

export default router
