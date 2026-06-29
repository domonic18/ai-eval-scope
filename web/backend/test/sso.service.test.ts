/**
 * SsoService 单元测试（docs/arch/12 §4）— 不依赖真实 DB / 不联网。
 *
 * mock 依赖：saml2-js（post_assert 注入构造断言）、prisma、UserRepository、config。
 * 覆盖：startLogin / handleAcs（新建、email 命中绑定、InResponseTo 防重放、非法断言、
 *      NameID 缺失）/ exchangeCode 一次性消费。
 */

import { vi, describe, it, expect, beforeEach } from "vitest"
import { SsoService, __resetSsoCacheForTest } from "../src/services/sso.service"

// ── mock 依赖（vi.hoisted 让 mock 工厂与测试共享可变状态）──
const mocks = vi.hoisted(() => {
  const saml = {
    response: null as Record<string, unknown> | null,
    error: null as Error | null,
    requestId: "mock-request-id",
  }
  const userRepo = {
    findByEmail: vi.fn(),
    findBySsoNameId: vi.fn(),
  }
  const prisma = {
    user: { create: vi.fn(), update: vi.fn() },
    organization: { create: vi.fn(), findUnique: vi.fn() },
    orgMembership: { create: vi.fn() },
    $transaction: vi.fn(async (fn: (tx: typeof prisma) => unknown) => fn(prisma)),
  }
  return { saml, userRepo, prisma }
})

vi.mock("saml2-js", () => {
  const ServiceProvider = class MockSP {
    create_login_request_url(_idp: unknown, _opts: unknown, cb: (e: Error | null, url: string, id: string) => void) {
      cb(null, "https://guanghua.test/idp/login?mock=1", mocks.saml.requestId)
    }
    post_assert(_idp: unknown, _opts: unknown, cb: (e: Error | null, r: unknown) => void) {
      cb(mocks.saml.error, mocks.saml.response)
    }
    create_metadata() {
      return "<EntityDescriptor mock/>"
    }
  }
  const IdentityProvider = class MockIdp {}
  // sso.service 用 `import saml2 from "saml2-js"`（default 导入），同时提供 default 与命名导出
  return { default: { ServiceProvider, IdentityProvider }, ServiceProvider, IdentityProvider }
})

vi.mock("../src/infra/prisma", () => ({
  getPrisma: () => mocks.prisma,
  disconnect: vi.fn(),
}))

vi.mock("../src/repositories/user.repository", () => ({
  // new UserRepository() 得到实例，方法指向共享 mocks.userRepo 的 vi.fn
  UserRepository: class MockUserRepository {
    findByEmail = mocks.userRepo.findByEmail
    findBySsoNameId = mocks.userRepo.findBySsoNameId
  },
}))

vi.mock("../src/config", () => ({
  getSamlConfig: () => ({
    enabled: true,
    spEntityId: "https://eval.test/api/v1/auth/sso/metadata",
    acsUrl: "https://eval.test/api/v1/auth/sso/acs",
    slsUrl: "https://eval.test/api/v1/auth/sso/sls",
    spCert: "",
    spKey: "",
    idpEntityId: "https://guanghua.test/idp/metadata",
    idpSsoUrl: "https://guanghua.test/idp/login",
    idpSlsUrl: "https://guanghua.test/idp/logout",
    idpCert: "MIICdummy",
    strict: true,
    debug: false,
  }),
  validateSamlConfig: () => [],
  getConfig: () => ({ jwtSecret: "unit-test-secret", keyEncryptionKey: "unit-test-kek" }),
}))

function setAssertion(p: { nameId: string; email?: string; inResponseTo?: string }) {
  mocks.saml.error = null
  mocks.saml.response = {
    response_header: { id: "resp-1", destination: "", in_response_to: p.inResponseTo ?? mocks.saml.requestId },
    type: "authn_response",
    user: { name_id: p.nameId, email: p.email, name: "U", attributes: {} },
  }
}

beforeEach(() => {
  __resetSsoCacheForTest() // 重置 SP/IdP 单例
  mocks.saml.response = null
  mocks.saml.error = null
  mocks.userRepo.findByEmail.mockReset()
  mocks.userRepo.findBySsoNameId.mockReset()
  mocks.prisma.user.create.mockReset()
  mocks.prisma.user.update.mockReset()
  mocks.prisma.organization.create.mockReset()
  mocks.prisma.organization.findUnique.mockReset()
  mocks.prisma.orgMembership.create.mockReset()
  mocks.prisma.$transaction.mockImplementation(async (fn: (tx: typeof mocks.prisma) => unknown) => fn(mocks.prisma))
})

describe("SsoService.isSsoEnabled / getMetadata", () => {
  it("isSsoEnabled reflects config", () => {
    expect(SsoService.isSsoEnabled()).toBe(true)
  })
  it("getMetadata returns SP metadata XML", () => {
    expect(SsoService.getMetadata()).toContain("EntityDescriptor")
  })
})

describe("SsoService.startLogin", () => {
  it("returns IdP redirect URL", async () => {
    const r = await SsoService.startLogin()
    expect(r.redirect_url).toContain("guanghua.test")
  })
})

describe("SsoService.handleAcs — 新建用户", () => {
  it("creates sso user (no personal org) when email/nameId both unmatched", async () => {
    mocks.userRepo.findByEmail.mockResolvedValue(null)
    mocks.userRepo.findBySsoNameId.mockResolvedValue(null)
    mocks.prisma.user.create.mockResolvedValue({ id: "u1", email: "x@y.z", name: "U" })

    await SsoService.startLogin() // remember request_id
    setAssertion({ nameId: "n1", email: "x@y.z" })
    const { code } = await SsoService.handleAcs("encoded-response")

    expect(mocks.prisma.user.create).toHaveBeenCalled()
    expect(mocks.prisma.organization.create).not.toHaveBeenCalled() // 不再建个人 Org
    expect(code).toMatch(/\S+/)

    const session = SsoService.exchangeCode(code)
    expect(session.access_token).toMatch(/\S+/)
    expect(session.user.email).toBe("x@y.z")
    expect(session.org).toBeUndefined() // 无团队，登录后创建/加入
  })
})

describe("SsoService.handleAcs — email 命中绑定", () => {
  it("updates existing user (no new user/org) when email matches", async () => {
    mocks.userRepo.findByEmail.mockResolvedValue({
      id: "u2",
      email: "e@y.z",
      passwordHash: "$argon2id$hash",
      ssoNameId: null,
      ssoProvider: null,
    })
    mocks.prisma.user.update.mockResolvedValue({
      id: "u2",
      email: "e@y.z",
      name: "U",
      passwordHash: "$argon2id$hash",
      authType: "saml",
      ssoNameId: "n2",
    })

    await SsoService.startLogin()
    setAssertion({ nameId: "n2", email: "e@y.z" })
    const { code } = await SsoService.handleAcs("encoded-response")

    expect(mocks.prisma.user.update).toHaveBeenCalledWith(expect.objectContaining({ where: { id: "u2" } }))
    expect(mocks.prisma.user.create).not.toHaveBeenCalled()
    expect(code).toMatch(/\S+/)
  })
})

describe("SsoService.handleAcs — nameId 命中", () => {
  it("updates login info when nameId matches an existing sso user", async () => {
    mocks.userRepo.findByEmail.mockResolvedValue(null) // email 不命中
    mocks.userRepo.findBySsoNameId.mockResolvedValue({ id: "u3", email: "p@y.z", name: "U", ssoNameId: "n3" })
    mocks.prisma.user.update.mockResolvedValue({ id: "u3", email: "p@y.z", name: "U", ssoNameId: "n3" })

    await SsoService.startLogin()
    setAssertion({ nameId: "n3", email: "other@y.z" })
    await SsoService.handleAcs("encoded-response")

    expect(mocks.prisma.user.update).toHaveBeenCalledWith(expect.objectContaining({ where: { id: "u3" } }))
    expect(mocks.prisma.user.create).not.toHaveBeenCalled()
  })
})

describe("SsoService.handleAcs — 防重放 / 非法断言", () => {
  it("rejects unknown InResponseTo (replay)", async () => {
    mocks.userRepo.findByEmail.mockResolvedValue(null)
    await SsoService.startLogin()
    setAssertion({ nameId: "n4", email: "r@y.z", inResponseTo: "stolen-id" })
    await expect(SsoService.handleAcs("encoded-response")).rejects.toMatchObject({ code: "SSO_REPLAY" })
    expect(mocks.prisma.user.create).not.toHaveBeenCalled()
  })

  it("rejects when post_assert errors (invalid signature)", async () => {
    mocks.saml.error = new Error("invalid signature")
    mocks.saml.response = null
    await SsoService.startLogin()
    await expect(SsoService.handleAcs("encoded-response")).rejects.toMatchObject({ code: "SSO_INVALID" })
  })

  it("rejects when NameID missing", async () => {
    mocks.saml.error = null
    mocks.saml.response = {
      response_header: { id: "r", destination: "", in_response_to: mocks.saml.requestId },
      type: "authn_response",
      user: { name_id: "", attributes: {} },
    }
    await SsoService.startLogin()
    await expect(SsoService.handleAcs("encoded-response")).rejects.toMatchObject({ code: "SSO_INVALID" })
  })
})

describe("SsoService.exchangeCode — 一次性消费", () => {
  it("issues a code that can be exchanged exactly once", async () => {
    mocks.userRepo.findByEmail.mockResolvedValue(null)
    mocks.userRepo.findBySsoNameId.mockResolvedValue(null)
    mocks.prisma.organization.findUnique.mockResolvedValue(null)
    mocks.prisma.user.create.mockResolvedValue({ id: "u5", email: "o@y.z", name: "U" })
    mocks.prisma.organization.create.mockResolvedValue({ id: "o5", name: "Org", slug: "o" })

    await SsoService.startLogin()
    setAssertion({ nameId: "n5", email: "o@y.z" })
    const { code } = await SsoService.handleAcs("encoded-response")

    expect(() => SsoService.exchangeCode(code)).not.toThrow()
    expect(() => SsoService.exchangeCode(code)).toThrow() // 第二次：已消费
  })

  it("unknown code throws", () => {
    expect(() => SsoService.exchangeCode("nonexistent")).toThrow()
  })
})
