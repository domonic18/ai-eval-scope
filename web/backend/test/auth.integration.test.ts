/**
 * 验证标准 #1 / #2 / #3 / #5（Sprint 7c）：
 *  #1 注册/登录/刷新可用，密码 argon2 哈希存储
 *  #2 创建项目签发 Key，secret 仅创建时返回一次，DB 仅存哈希/加密态
 *  #3 跨租户隔离（枚举 / 直查 / 越权写 三类用例）
 *  #5 敏感操作落审计日志
 */

import request from "supertest"
import { createApp } from "../src/server"
import { getPrisma } from "../src/infra/prisma"
import { decryptToken } from "../src/infra/crypto"
import { registerUser, login, createProject, issueKey } from "./helpers"

let app: ReturnType<typeof createApp>
beforeAll(() => {
  app = createApp()
})

const prisma = getPrisma()

describe("#1 注册 / 登录 / 刷新 + argon2 哈希", () => {
  it("registers, stores argon2id hash, issues JWT pair", async () => {
    const u = await registerUser(app, "a1")
    expect(u.accessToken).toMatch(/\S+/)
    expect(u.org.id).toBeDefined()

    const row = await prisma.user.findUnique({ where: { id: u.user.id } })
    expect(row!.passwordHash!.startsWith("$argon2id")).toBe(true)
  })

  it("logs in with correct password and gets an access token", async () => {
    const u = await registerUser(app, "a2")
    const sess = await login(app, u.email)
    expect(sess.access_token).toBeDefined()
  })

  it("rejects login with wrong password (401 AUTH_INVALID)", async () => {
    const u = await registerUser(app, "a3")
    const r = await request(app)
      .post("/api/v1/auth/login")
      .send({ email: u.email, password: "wrong-password" })
    expect(r.status).toBe(401)
    expect(r.body.code).toBe("AUTH_INVALID")
  })
})

describe("#2 项目 + API Key：token 仅返回一次，DB 仅存哈希/加密态", () => {
  it("issues a key with plaintext token (once) and stores hash+encrypted only", async () => {
    const u = await registerUser(app, "b1")
    const project = await createProject(app, u)
    const key = await issueKey(app, { accessToken: u.accessToken, projectId: project.id })

    expect(key.token).toMatch(/^eval-/) // 明文，仅本次返回

    const row = await prisma.apiKey.findUnique({ where: { id: key.id } })
    expect(row!.tokenHash).toMatch(/^[0-9a-f]{64}$/) // sha256
    expect(row!.tokenEncrypted.startsWith("v1:")).toBe(true) // AES-GCM
    expect(row!.tokenEncrypted).not.toContain(key.token)
    expect(row!.callCount.toString()).toBe("0")
    // 方案 A：加密态可还原为明文（executor 回传解密）
    expect(decryptToken(row!.tokenEncrypted)).toBe(key.token)
  })

  it("list keys never returns plaintext or reversible token", async () => {
    const u = await registerUser(app, "b2")
    const project = await createProject(app, u)
    await issueKey(app, { accessToken: u.accessToken, projectId: project.id })

    const r = await request(app)
      .get(`/api/v1/projects/${project.id}/keys`)
      .set("Authorization", `Bearer ${u.accessToken}`)
    expect(r.status).toBe(200)
    expect(r.body.keys.length).toBe(1)
    const k = r.body.keys[0]
    expect(k.token).toBeUndefined()
    expect(k.tokenHash).toBeUndefined()
    expect(k.tokenEncrypted).toBeUndefined()
    expect(k.tokenPreview).toMatch(/^eval-/)
  })
})

describe("#3 跨租户隔离（A 组织用户无法访问 B 组织数据）", () => {
  let a: Awaited<ReturnType<typeof registerUser>>
  let b: Awaited<ReturnType<typeof registerUser>>
  let projectB: Awaited<ReturnType<typeof createProject>>
  beforeAll(async () => {
    a = await registerUser(app, "isoA")
    b = await registerUser(app, "isoB")
    projectB = await createProject(app, b)
  })

  it("枚举：A 无法列出 B 组织的项目（orgGuard → 404）", async () => {
    const r = await request(app)
      .get(`/api/v1/orgs/${b.org.id}/projects`)
      .set("Authorization", `Bearer ${a.accessToken}`)
    expect(r.status).toBe(404)
  })

  it("枚举：A 无法列出 B 组织的成员（orgGuard → 404）", async () => {
    const r = await request(app)
      .get(`/api/v1/orgs/${b.org.id}/members`)
      .set("Authorization", `Bearer ${a.accessToken}`)
    expect(r.status).toBe(404)
  })

  it("直查：A 无法读取 B 的项目详情（projectGuard → 404）", async () => {
    const r = await request(app)
      .get(`/api/v1/projects/${projectB.id}`)
      .set("Authorization", `Bearer ${a.accessToken}`)
    expect(r.status).toBe(404)
  })

  it("越权写：A 无法在 B 的项目下签发 Key（projectGuard → 404）", async () => {
    const r = await request(app)
      .post(`/api/v1/projects/${projectB.id}/keys`)
      .set("Authorization", `Bearer ${a.accessToken}`)
      .send({ name: "stolen" })
    expect(r.status).toBe(404)
  })

  it("越权写：A 无法向 B 组织邀请成员（orgGuard → 404）", async () => {
    const r = await request(app)
      .post(`/api/v1/orgs/${b.org.id}/members`)
      .set("Authorization", `Bearer ${a.accessToken}`)
      .send({ email: a.email, role: "member" })
    expect(r.status).toBe(404)
  })

  it("无 token 访问受保护路由 → 401", async () => {
    const r = await request(app).get(`/api/v1/projects/${projectB.id}`)
    expect(r.status).toBe(401)
  })
})

describe("#5 敏感操作落审计日志", () => {
  it("logs key.create / project.archive / member.invite", async () => {
    const owner = await registerUser(app, "aud")
    const project = await createProject(app, owner)
    await issueKey(app, { accessToken: owner.accessToken, projectId: project.id })

    const invitee = await registerUser(app, "audinv")
    await request(app)
      .post(`/api/v1/orgs/${owner.org.id}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ email: invitee.email, role: "member" })

    await request(app)
      .post(`/api/v1/projects/${project.id}/archive`)
      .set("Authorization", `Bearer ${owner.accessToken}`)

    const logs = await prisma.auditLog.findMany({
      where: { orgId: owner.org.id },
      orderBy: { createdAt: "asc" },
    })
    const actions = logs.map((l) => l.action)
    expect(actions).toContain("key.create")
    expect(actions).toContain("member.invite")
    expect(actions).toContain("project.archive")
    expect(logs.every((l) => l.actorUserId === owner.user.id)).toBe(true)
  })
})
