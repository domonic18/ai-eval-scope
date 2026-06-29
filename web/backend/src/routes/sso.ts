/**
 * SAML SSO 路由（/api/v1/auth/sso），docs/arch/12 §4.3。
 *
 *  - GET  /config     SSO 启用状态（前端据此显示 Tab）
 *  - GET  /metadata   SP Metadata XML（联调/备案；光华不强制要求）
 *  - POST /login      发起 SSO → 返回光华跳转 URL
 *  - POST /acs        光华 ACS 回调（HTTP-POST binding，form-urlencoded SAMLResponse）
 *                     → 验签/建号/签 JWT → 302 前端 /login?sso=success&code=xxx
 *  - POST /exchange   一次性 code 换 token pair（前端在 /login?sso=success 调用）
 *
 * ACS 由浏览器载体 POST（光华返回自动提交的 form），错误时统一 302 到
 * /login?sso=error&reason=... 让前端友好提示，而非返回 JSON 错误体。
 */

import express, { type RequestHandler } from "express"
import { SsoService } from "../services/sso.service"

const router = express.Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

// GET /config — 前端据此决定是否显示 SSO Tab
router.get("/config", (_req, res) => {
  res.json({ enabled: SsoService.isSsoEnabled() })
})

// GET /metadata — SP Metadata XML
router.get(
  "/metadata",
  wrap((_req, res) => {
    res.type("application/xml").send(SsoService.getMetadata())
  }),
)

// POST /login — 发起 SSO，返回光华跳转 URL（前端 window.location 跳转）
router.post(
  "/login",
  wrap(async (_req, res) => {
    const { redirect_url } = await SsoService.startLogin()
    res.json({ redirect_url })
  }),
)

// POST /acs — 光华 ACS 回调（form-urlencoded）。成功/失败均 302 到前端。
router.post(
  "/acs",
  express.urlencoded({ extended: true, limit: "1mb" }),
  wrap(async (req, res) => {
    const samlResponse: unknown = req.body?.SAMLResponse
    try {
      if (typeof samlResponse !== "string" || !samlResponse) {
        throw new Error("missing SAMLResponse")
      }
      const { code } = await SsoService.handleAcs(samlResponse)
      res.redirect(302, `/login?sso=success&code=${encodeURIComponent(code)}`)
    } catch (e) {
      const reason = encodeURIComponent(e instanceof Error ? e.message : "acs_failed")
      res.redirect(302, `/login?sso=error&reason=${reason}`)
    }
  }),
)

// POST /exchange — 一次性 code 换 token pair
router.post(
  "/exchange",
  wrap((req, res) => {
    const code: unknown = req.body?.code
    if (typeof code !== "string" || !code) {
      res.status(400).json({ error: "missing code", code: "SSO_CODE_INVALID" })
      return
    }
    res.json(SsoService.exchangeCode(code))
  }),
)

export default router
