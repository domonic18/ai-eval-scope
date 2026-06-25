/**
 * 制品路由（/api/v1/artifacts）。
 *  - GET /:id        校验归属后 302 重定向到 presigned GET（下载/新窗口，attachment 语义）
 *  - GET /:id/preview  返回预览 URL + 元信息（JSON，前端 iframe/fetch 用）：
 *                      image→COS presigned 直链；其余→同源 raw 代理（规避 COS 强制下载）
 *  - GET /:id/raw    同源流式代理：token 鉴权后拉取对象，强制 inline + 正确 Content-Type 回吐
 */

import { Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { artifactGuard } from "../middleware/tenantGuard"
import { PlatformError } from "../middleware/errorHandler"
import { createQueryService } from "../services/query.service"
import {
  issueArtifactToken,
  verifyArtifactToken,
  type ArtifactTokenClaims,
} from "../infra/crypto"
import { getObjectStorage } from "../infra/objectStorage"
import { getConfig } from "../config"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

/** 拉取制品对象；对象不存在转 404，其余错误原样抛出。 */
async function fetchArtifactObject(key: string): Promise<Buffer> {
  try {
    return await getObjectStorage().get({ key })
  } catch (err) {
    const e = err as { $metadata?: { httpStatusCode?: number }; name?: string }
    if (e.$metadata?.httpStatusCode === 404 || (e.name && /NoSuch|NotFound/i.test(e.name))) {
      throw new PlatformError("artifact object not found", { status: 404, code: "NOT_FOUND" })
    }
    throw err
  }
}

/** 校验 raw 代理 token，失败统一转 401。 */
function requireArtifactToken(token: string): ArtifactTokenClaims {
  try {
    return verifyArtifactToken(token)
  } catch {
    throw new PlatformError("invalid or expired artifact token", {
      status: 401,
      code: "AUTH_INVALID",
    })
  }
}

router.get(
  "/:id",
  requireAuth,
  artifactGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!)
    const meta = await svc.artifactMeta(req.params.id)
    const g = await getObjectStorage().presignGet({
      key: meta.objectKey,
      ttlSec: getConfig().presignTtlSec,
    })
    res.redirect(302, g.url)
  }),
)

router.get(
  "/:id/preview",
  requireAuth,
  artifactGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!)
    const meta = await svc.artifactMeta(req.params.id)
    let url: string
    if (meta.contentType.startsWith("image")) {
      // image：COS presigned 直链（img 标签不触发下载、省函数流量、规避 SCF 响应大小上限）
      const g = await getObjectStorage().presignGet({
        key: meta.objectKey,
        ttlSec: getConfig().presignTtlSec,
      })
      url = g.url
    } else {
      // html/text/trace：同源 raw 代理（规避 COS 默认 attachment 下载 + 跨域 fetch CORS）
      const token = issueArtifactToken({
        artifactId: req.params.id,
        objectKey: meta.objectKey,
        contentType: meta.contentType,
        filename: meta.filename,
      })
      url = `/api/v1/artifacts/${req.params.id}/raw?token=${token}`
    }
    res.json({ url, contentType: meta.contentType, filename: meta.filename })
  }),
)

// 同源流式代理：iframe/fetch 直接加载。iframe 导航不带 Authorization，故由 preview 端点
// 签发的专用短期 token 鉴权；强制 inline + 正确 Content-Type，绕开 COS response-* 覆盖失效。
router.get(
  "/:id/raw",
  wrap(async (req, res) => {
    const token = req.query.token
    if (typeof token !== "string" || !token) {
      throw new PlatformError("missing artifact token", { status: 401, code: "AUTH_INVALID" })
    }
    const claims = requireArtifactToken(token)
    if (claims.aid !== req.params.id) {
      throw new PlatformError("artifact token mismatch", { status: 403, code: "FORBIDDEN" })
    }
    const body = await fetchArtifactObject(claims.key)
    res.setHeader("X-Content-Type-Options", "nosniff")
    res.setHeader("Content-Disposition", "inline")
    res.setHeader("Cache-Control", "private, no-store")
    res.setHeader(
      "Content-Type",
      claims.ct.includes("html") ? "text/html; charset=utf-8" : claims.ct,
    )
    res.status(200).send(body)
  }),
)

export default router
