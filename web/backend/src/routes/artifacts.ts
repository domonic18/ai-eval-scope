/**
 * 制品路由（/api/v1/artifacts）。
 *  - GET /:id       校验归属后 302 重定向到 presigned GET（下载用）
 *  - GET /:id/preview  返回 inline presigned URL + 元信息（JSON，前端 iframe/fetch 用；强制 inline 规避下载）
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
    // 预览强制 inline（html 额外覆盖 text/html），避免 COS 返回
    // Content-Disposition: attachment 触发浏览器下载、iframe 空白
    const dl = await svc.artifactDownload(req.params.id, { inline: true })
    res.json({ url: dl.url, contentType: dl.contentType, filename: dl.filename })
  }),
)

export default router
