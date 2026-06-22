/** 7c 测试公共辅助：注册用户、建项目、签发 Key。 */

import request from "supertest"
import type { Application } from "express"
import { signHmac, authHeader } from "../src/infra/crypto"

let _counter = 0
function uniq(prefix: string): string {
  _counter += 1
  return `${prefix}${Date.now()}_${_counter}`
}
function tag(): string {
  return Math.random().toString(36).slice(2, 8)
}

export interface RegisteredUser {
  email: string
  accessToken: string
  refreshToken: string
  user: { id: string; email: string; name: string | null }
  org: { id: string; name: string; slug: string }
}

export async function registerUser(
  app: Application,
  t: string,
  opts: { password?: string; name?: string; orgName?: string } = {},
): Promise<RegisteredUser> {
  const email = `${uniq("u")}_${t}@example.com`
  const r = await request(app)
    .post("/api/v1/auth/register")
    .send({
      email,
      password: opts.password || "password123",
      name: opts.name || `User-${t}`,
      orgName: opts.orgName || `Org-${t}`,
    })
  if (r.status !== 201) throw new Error(`register failed: ${r.status} ${JSON.stringify(r.body)}`)
  return {
    email,
    accessToken: r.body.access_token,
    refreshToken: r.body.refresh_token,
    user: r.body.user,
    org: r.body.org,
  }
}

export async function login(app: Application, email: string, password = "password123") {
  const r = await request(app).post("/api/v1/auth/login").send({ email, password })
  if (r.status !== 200) throw new Error(`login failed: ${r.status}`)
  return r.body
}

export async function createProject(
  app: Application,
  user: RegisteredUser,
  opts: { name?: string; slug?: string } = {},
) {
  const orgId = user.org.id
  if (!orgId) throw new Error("createProject: orgId missing on user")
  const r = await request(app)
    .post(`/api/v1/orgs/${orgId}/projects`)
    .set("Authorization", `Bearer ${user.accessToken}`)
    .send({ name: opts.name || `Proj-${tag()}`, slug: opts.slug || uniq("p") })
  if (r.status !== 201)
    throw new Error(`createProject failed: ${r.status} ${JSON.stringify(r.body)}`)
  return r.body.project
}

export async function issueKey(
  app: Application,
  ctx: { accessToken: string; projectId: string },
  name = "key",
) {
  const r = await request(app)
    .post(`/api/v1/projects/${ctx.projectId}/keys`)
    .set("Authorization", `Bearer ${ctx.accessToken}`)
    .send({ name })
  if (r.status !== 201) throw new Error(`issueKey failed: ${r.status} ${JSON.stringify(r.body)}`)
  return r.body.key as {
    id: string
    publicKey: string
    secretKey: string
    name: string
  }
}

/** 用 HMAC 签名并发送（保证 rawBody 与签名字节一致）。 */
export async function signedPost(
  app: Application,
  p: { url: string; secretKey: string; publicKey: string; bodyObj: unknown },
) {
  const body = JSON.stringify(p.bodyObj)
  const sig = signHmac(p.secretKey, "POST", p.url, Buffer.from(body))
  return request(app)
    .post(p.url)
    .type("json")
    .send(body)
    .set("Authorization", authHeader(p.publicKey, sig))
}
