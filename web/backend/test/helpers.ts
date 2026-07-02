/** 7c 测试公共辅助：注册用户、建项目、签发 Key。 */

import request from "supertest"
import type { Application } from "express"

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
    })
  if (r.status !== 201) throw new Error(`register failed: ${r.status} ${JSON.stringify(r.body)}`)
  const accessToken: string = r.body.access_token
  // 团队改造后注册不再自动建团队；测试显式创建一个团队给该用户
  const orgRes = await request(app)
    .post("/api/v1/orgs")
    .set("Authorization", `Bearer ${accessToken}`)
    .send({ name: opts.orgName || `Org-${t}` })
  if (orgRes.status !== 201) {
    throw new Error(`createOrg failed: ${orgRes.status} ${JSON.stringify(orgRes.body)}`)
  }
  const org = orgRes.body.org
  return {
    email,
    accessToken,
    user: r.body.user,
    org: { id: org.id, name: org.name, slug: org.slug },
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
    token: string
    tokenPreview: string
    name: string
  }
}

/** Bearer 鉴权 POST（单一 token）。 */
export async function bearerPost(
  app: Application,
  p: { url: string; token: string; bodyObj: unknown },
) {
  return request(app)
    .post(p.url)
    .type("json")
    .send(p.bodyObj as object)
    .set("Authorization", `Bearer ${p.token}`)
}
