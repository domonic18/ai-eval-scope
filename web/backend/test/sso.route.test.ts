/**
 * SSO 路由接口级测试（docs/arch/12 §4.3）— 不依赖真实 DB / 不联网。
 *
 * mock SsoService，用 supertest 打 createApp，验证 /config /metadata /login /acs /exchange
 * 的 HTTP 行为（状态码、302 重定向、参数校验、错误透传）。
 */

import { vi, describe, it, expect, beforeAll, beforeEach } from "vitest"
import request from "supertest"
import type { Application } from "express"
import { PlatformError } from "../src/middleware/errorHandler"

// ── mock SsoService（接口级测试只验证路由层转发/编解码/错误处理）──
// 用 vi.hoisted：vi.mock 工厂被提升到顶部，须用 hoisted 变量避免 TDZ
const mockSsoService = vi.hoisted(() => ({
  isSsoEnabled: vi.fn(),
  getMetadata: vi.fn(),
  startLogin: vi.fn(),
  handleAcs: vi.fn(),
  exchangeCode: vi.fn(),
}))

vi.mock("../src/services/sso.service", () => ({ SsoService: mockSsoService }))

import { createApp } from "../src/server"

let app: Application

beforeAll(() => {
  app = createApp()
})

beforeEach(() => {
  mockSsoService.isSsoEnabled.mockReset()
  mockSsoService.getMetadata.mockReset()
  mockSsoService.startLogin.mockReset()
  mockSsoService.handleAcs.mockReset()
  mockSsoService.exchangeCode.mockReset()
})

describe("GET /api/v1/auth/sso/config", () => {
  it("returns enabled=true", async () => {
    mockSsoService.isSsoEnabled.mockReturnValue(true)
    const r = await request(app).get("/api/v1/auth/sso/config")
    expect(r.status).toBe(200)
    expect(r.body).toEqual({ enabled: true })
  })

  it("returns enabled=false when disabled", async () => {
    mockSsoService.isSsoEnabled.mockReturnValue(false)
    const r = await request(app).get("/api/v1/auth/sso/config")
    expect(r.body).toEqual({ enabled: false })
  })
})

describe("GET /api/v1/auth/sso/metadata", () => {
  it("returns SP metadata XML", async () => {
    mockSsoService.getMetadata.mockReturnValue("<EntityDescriptor mock/>")
    const r = await request(app).get("/api/v1/auth/sso/metadata")
    expect(r.status).toBe(200)
    expect(r.headers["content-type"]).toMatch(/xml/)
    expect(r.text).toContain("EntityDescriptor")
  })
})

describe("POST /api/v1/auth/sso/login", () => {
  it("returns redirect_url from service", async () => {
    mockSsoService.startLogin.mockResolvedValue({ redirect_url: "https://guanghua.test/idp/login?x=1" })
    const r = await request(app).post("/api/v1/auth/sso/login")
    expect(r.status).toBe(200)
    expect(r.body).toEqual({ redirect_url: "https://guanghua.test/idp/login?x=1" })
  })

  it("propagates SSO_DISABLED (503) when service throws PlatformError", async () => {
    mockSsoService.startLogin.mockRejectedValue(
      new PlatformError("SSO disabled", { status: 503, code: "SSO_DISABLED" }),
    )
    const r = await request(app).post("/api/v1/auth/sso/login")
    expect(r.status).toBe(503)
    expect(r.body.code).toBe("SSO_DISABLED")
  })
})

describe("POST /api/v1/auth/sso/acs", () => {
  it("redirects to /login?sso=success&code=... on success", async () => {
    mockSsoService.handleAcs.mockResolvedValue({ code: "abc123" })
    const r = await request(app).post("/api/v1/auth/sso/acs").type("form").send({ SAMLResponse: "encoded" })
    expect(r.status).toBe(302)
    expect(r.header.location).toBe("/login?sso=success&code=abc123")
  })

  it("redirects to /login?sso=error when handleAcs throws", async () => {
    mockSsoService.handleAcs.mockRejectedValue(new Error("invalid signature"))
    const r = await request(app).post("/api/v1/auth/sso/acs").type("form").send({ SAMLResponse: "encoded" })
    expect(r.status).toBe(302)
    expect(r.header.location).toMatch(/sso=error/)
  })

  it("redirects to sso=error when SAMLResponse missing", async () => {
    const r = await request(app).post("/api/v1/auth/sso/acs").type("form").send({})
    expect(r.status).toBe(302)
    expect(r.header.location).toMatch(/sso=error/)
    expect(mockSsoService.handleAcs).not.toHaveBeenCalled()
  })

  it("encodes code safely in redirect location", async () => {
    mockSsoService.handleAcs.mockResolvedValue({ code: "a b+/=" })
    const r = await request(app).post("/api/v1/auth/sso/acs").type("form").send({ SAMLResponse: "x" })
    expect(r.header.location).toBe("/login?sso=success&code=a%20b%2B%2F%3D")
  })
})

describe("POST /api/v1/auth/sso/exchange", () => {
  it("returns token pair for valid code", async () => {
    mockSsoService.exchangeCode.mockReturnValue({
      access_token: "at",
      refresh_token: "rt",
      expires_in: 1800,
      user: { id: "u", email: "a@b.c", name: null },
    })
    const r = await request(app).post("/api/v1/auth/sso/exchange").send({ code: "good" })
    expect(r.status).toBe(200)
    expect(r.body.access_token).toBe("at")
    expect(mockSsoService.exchangeCode).toHaveBeenCalledWith("good")
  })

  it("returns 400 when code missing", async () => {
    const r = await request(app).post("/api/v1/auth/sso/exchange").send({})
    expect(r.status).toBe(400)
    expect(mockSsoService.exchangeCode).not.toHaveBeenCalled()
  })

  it("propagates SSO_CODE_INVALID (401) for expired/unknown code", async () => {
    mockSsoService.exchangeCode.mockImplementation(() => {
      throw new PlatformError("invalid or expired sso code", { status: 401, code: "SSO_CODE_INVALID" })
    })
    const r = await request(app).post("/api/v1/auth/sso/exchange").send({ code: "stale" })
    expect(r.status).toBe(401)
    expect(r.body.code).toBe("SSO_CODE_INVALID")
  })
})
