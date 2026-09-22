/**
 * 成员管理集成测试：GET members 放宽（成员可读）+ PATCH 角色变更/所有权转移。
 * 前置：本地 postgres（make docker-up && make db-init），与 CI 同口径直连真库。
 */

import { afterEach, describe, expect, it } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { registerUser, type RegisteredUser } from "./helpers"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const ORG_IDS: string[] = []
const USER_EMAILS: string[] = []

function track(u: { email: string; org: { id: string } }) {
  USER_EMAILS.push(u.email)
  ORG_IDS.push(u.org.id)
}

/** 注册 owner + 邀请 member 入同一组织（member 复用注册自带的独立组织）。 */
async function setupOwnerMember(
  app: ReturnType<typeof createApp>,
  t: string,
): Promise<{ owner: RegisteredUser; member: RegisteredUser }> {
  const owner = await registerUser(app, `${t}-own`)
  track(owner)
  const member = await registerUser(app, `${t}-mem`)
  track(member)
  const invite = await request(app)
    .post(`/api/v1/orgs/${owner.org.id}/members`)
    .set("Authorization", `Bearer ${owner.accessToken}`)
    .send({ email: member.email })
  expect(invite.status).toBe(201)
  return { owner, member }
}

function memberUrl(orgId: string, userId: string) {
  return `/api/v1/orgs/${orgId}/members/${userId}`
}

afterEach(async () => {
  for (const id of ORG_IDS) await prisma.organization.deleteMany({ where: { id } }).catch(() => {})
  for (const email of USER_EMAILS) await prisma.user.deleteMany({ where: { email } }).catch(() => {})
  ORG_IDS.length = 0
  USER_EMAILS.length = 0
})

describe("GET /orgs/:org/members 放宽", () => {
  it("owner 200、member 200（含 name/joinedAt）、非成员 404、未登录 401", async () => {
    const app = createApp()
    const { owner, member } = await setupOwnerMember(app, "mg-get")
    const base = `/api/v1/orgs/${owner.org.id}/members`

    const ownerList = await request(app)
      .get(base)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(ownerList.status).toBe(200)
    expect(ownerList.body.members).toHaveLength(2)

    const memberList = await request(app)
      .get(base)
      .set("Authorization", `Bearer ${member.accessToken}`)
    expect(memberList.status).toBe(200)
    const row = memberList.body.members.find(
      (m: { userId: string }) => m.userId === member.user.id,
    )
    expect(row.role).toBe("member")
    expect(row.email).toBe(member.email)
    expect(row.name).toBeTruthy()
    expect(row.joinedAt).toBeTruthy()

    const outsider = await registerUser(app, "mg-out")
    track(outsider)
    expect(
      (
        await request(app).get(base).set("Authorization", `Bearer ${outsider.accessToken}`)
      ).status,
    ).toBe(404)
    expect((await request(app).get(base)).status).toBe(401)
  })
})

describe("PATCH /orgs/:org/members/:userId", () => {
  it("升级 member → owner：双方均 owner", async () => {
    const app = createApp()
    const { owner, member } = await setupOwnerMember(app, "mg-promote")
    const patch = await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ role: "owner" })
    expect(patch.status).toBe(200)
    expect(patch.body).toMatchObject({ userId: member.user.id, role: "owner", selfDemoted: false })

    const list = await request(app)
      .get(`/api/v1/orgs/${owner.org.id}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    const roles = Object.fromEntries(
      list.body.members.map((m: { userId: string; role: string }) => [m.userId, m.role]),
    )
    expect(roles[owner.user.id]).toBe("owner")
    expect(roles[member.user.id]).toBe("owner")
  })

  it("降级另一 owner → member：调用方仍 owner（不变量保持）", async () => {
    const app = createApp()
    const { owner, member } = await setupOwnerMember(app, "mg-demote")
    await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ role: "owner" })
    const patch = await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ role: "member" })
    expect(patch.status).toBe(200)
    expect(patch.body.role).toBe("member")

    const list = await request(app)
      .get(`/api/v1/orgs/${owner.org.id}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    const roles = Object.fromEntries(
      list.body.members.map((m: { userId: string; role: string }) => [m.userId, m.role]),
    )
    expect(roles[owner.user.id]).toBe("owner")
    expect(roles[member.user.id]).toBe("member")
  })

  it("所有权转移：A 提升 B + demoteSelf → 角色反转，A 后续管理操作 403", async () => {
    const app = createApp()
    const { owner, member } = await setupOwnerMember(app, "mg-transfer")
    const patch = await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ role: "owner", demoteSelf: true })
    expect(patch.status).toBe(200)
    expect(patch.body).toMatchObject({ userId: member.user.id, role: "owner", selfDemoted: true })

    const list = await request(app)
      .get(`/api/v1/orgs/${owner.org.id}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(list.status).toBe(200) // member 仍可读
    const roles = Object.fromEntries(
      list.body.members.map((m: { userId: string; role: string }) => [m.userId, m.role]),
    )
    expect(roles[owner.user.id]).toBe("member")
    expect(roles[member.user.id]).toBe("owner")

    // 原 owner 已降级：管理操作被 orgGuard 拒绝（403）
    const retry = await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ role: "member" })
    expect(retry.status).toBe(403)
    const invite = await request(app)
      .post(`/api/v1/orgs/${owner.org.id}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ email: "nobody@example.com" })
    expect(invite.status).toBe(403)
  })

  it("权限：member PATCH 403、非成员 PATCH 404", async () => {
    const app = createApp()
    const { owner, member } = await setupOwnerMember(app, "mg-perm")
    const memberPatch = await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set("Authorization", `Bearer ${member.accessToken}`)
      .send({ role: "owner" })
    expect(memberPatch.status).toBe(403)

    const outsider = await registerUser(app, "mg-perm-out")
    track(outsider)
    const outsiderPatch = await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set("Authorization", `Bearer ${outsider.accessToken}`)
      .send({ role: "owner" })
    expect(outsiderPatch.status).toBe(404)
  })

  it("参数防呆：改自己/非法 role/缺 role/唯一 owner 退位无继任 均 400", async () => {
    const app = createApp()
    const { owner, member } = await setupOwnerMember(app, "mg-guard")
    const auth = { Authorization: `Bearer ${owner.accessToken}` }

    const selfPatch = await request(app)
      .patch(memberUrl(owner.org.id, owner.user.id))
      .set(auth)
      .send({ role: "member", demoteSelf: true })
    expect(selfPatch.status).toBe(400)
    expect(selfPatch.body.code).toBe("CONFLICT")

    const badRole = await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set(auth)
      .send({ role: "admin" })
    expect(badRole.status).toBe(400)
    expect(badRole.body.code).toBe("SCHEMA_INVALID")

    const noRole = await request(app).patch(memberUrl(owner.org.id, member.user.id)).set(auth).send({})
    expect(noRole.status).toBe(400)

    const selfDemoteNoSuccessor = await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set(auth)
      .send({ role: "member", demoteSelf: true })
    expect(selfDemoteNoSuccessor.status).toBe(400)
    expect(selfDemoteNoSuccessor.body.code).toBe("CONFLICT") // 唯一 owner 退位且目标仍 member → 零 owner
  })

  it("跨组织 userId 404（target 存在但未加入本组织）", async () => {
    const app = createApp()
    const { owner } = await setupOwnerMember(app, "mg-cross")
    const outsider = await registerUser(app, "mg-cross-out")
    track(outsider)
    // outsider 在自己的注册组织里有 membership，但对 owner 组织是未知成员
    const patch = await request(app)
      .patch(memberUrl(owner.org.id, outsider.user.id))
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ role: "owner" })
    expect(patch.status).toBe(404)
    expect(patch.body.code).toBe("NOT_FOUND")
  })

  it("同角色幂等：200 且数据不变", async () => {
    const app = createApp()
    const { owner, member } = await setupOwnerMember(app, "mg-idem")
    const patch = await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ role: "member" })
    expect(patch.status).toBe(200)
    expect(patch.body).toMatchObject({ userId: member.user.id, role: "member", selfDemoted: false })

    const audit = await prisma.auditLog.findMany({
      where: { orgId: owner.org.id, action: "member.update_role" },
    })
    expect(audit).toHaveLength(0) // no-op 不审计
  })

  it("成功变更落审计 member.update_role", async () => {
    const app = createApp()
    const { owner, member } = await setupOwnerMember(app, "mg-audit")
    await request(app)
      .patch(memberUrl(owner.org.id, member.user.id))
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ role: "owner" })
    const audit = await prisma.auditLog.findMany({
      where: { orgId: owner.org.id, action: "member.update_role" },
    })
    expect(audit).toHaveLength(1)
    expect(audit[0].targetId).toBe(member.user.id)
    expect(audit[0].actorUserId).toBe(owner.user.id)
  })
})

describe("邀请（未注册邮箱 → 待接受 → 注册自动加入）", () => {
  let _invSeq = 0
  /** 生成唯一邀请邮箱（helpers 的 uniq/tag 未导出）。 */
  function invitedEmail(prefix: string): string {
    _invSeq += 1
    return `${prefix}${Date.now()}_${_invSeq}@example.com`
  }

  /** 用原始请求注册指定邮箱（registerUser helper 的邮箱是随机生成的）。 */
  async function registerEmail(
    app: ReturnType<typeof createApp>,
    email: string,
    t: string,
  ): Promise<{ accessToken: string; userId: string }> {
    const r = await request(app)
      .post("/api/v1/auth/register")
      .send({ email, password: "password123", name: `Invited-${t}` })
    expect(r.status).toBe(201)
    USER_EMAILS.push(email)
    return { accessToken: r.body.access_token, userId: r.body.user.id }
  }

  it("邀请未注册邮箱 → 待接受列表；重复邀请 409；重发刷新 resentAt；撤回后不可见", async () => {
    const app = createApp()
    const owner = await registerUser(app, "inv-own")
    track(owner)
    const orgId = owner.org.id
    const invitedEmailStr = invitedEmail("inv")

    const invite = await request(app)
      .post(`/api/v1/orgs/${orgId}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ email: invitedEmailStr, role: "member" })
    expect(invite.status).toBe(201)
    expect(invite.body.member).toMatchObject({ kind: "invitation", email: invitedEmailStr })

    // 重复邀请 → 409
    const dup = await request(app)
      .post(`/api/v1/orgs/${orgId}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ email: invitedEmailStr })
    expect(dup.status).toBe(409)

    // 待接受列表（含邀请人）
    const list = await request(app)
      .get(`/api/v1/orgs/${orgId}/invitations`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(list.status).toBe(200)
    expect(list.body.invitations).toHaveLength(1)
    expect(list.body.invitations[0]).toMatchObject({
      email: invitedEmailStr,
      role: "member",
    })
    expect(list.body.invitations[0].inviter.email).toBe(owner.email)

    // 重发 → resentAt 刷新
    const invId = list.body.invitations[0].id
    const resend = await request(app)
      .post(`/api/v1/orgs/${orgId}/invitations/${invId}/resend`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(resend.status).toBe(200)
    const afterResend = await request(app)
      .get(`/api/v1/orgs/${orgId}/invitations`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(afterResend.body.invitations[0].resentAt).not.toBeNull()

    // 撤回 → 列表不再可见
    const revoke = await request(app)
      .post(`/api/v1/orgs/${orgId}/invitations/${invId}/revoke`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(revoke.status).toBe(200)
    const afterRevoke = await request(app)
      .get(`/api/v1/orgs/${orgId}/invitations`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(afterRevoke.body.invitations).toHaveLength(0)
  })

  it("受邀邮箱注册 → 自动加入组织并从待接受列表移除；成员行带 lastActive", async () => {
    const app = createApp()
    const owner = await registerUser(app, "inv-acc")
    track(owner)
    const orgId = owner.org.id
    const invitedEmailStr = invitedEmail("acc")

    await request(app)
      .post(`/api/v1/orgs/${orgId}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ email: invitedEmailStr })
    const listed = await request(app)
      .get(`/api/v1/orgs/${orgId}/invitations`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    const invId = listed.body.invitations[0].id

    // 受邀者注册（不建自己的团队）→ 自动加入 owner 团队
    const invited = await registerEmail(app, invitedEmailStr, "acc")

    const members = await request(app)
      .get(`/api/v1/orgs/${orgId}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    const row = members.body.members.find((m: { email: string }) => m.email === invitedEmailStr)
    expect(row).toBeTruthy()
    expect(row.role).toBe("member")
    expect(row.lastActive).toBeTruthy()

    const pending = await request(app)
      .get(`/api/v1/orgs/${orgId}/invitations`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(pending.body.invitations).toHaveLength(0)

    // 受邀者现在能以成员身份读成员列表
    expect(
      (
        await request(app)
          .get(`/api/v1/orgs/${orgId}/members`)
          .set("Authorization", `Bearer ${invited.accessToken}`)
      ).status,
    ).toBe(200)

    // 已 accepted 的邀请不可再撤回
    const revoke = await request(app)
      .post(`/api/v1/orgs/${orgId}/invitations/${invId}/revoke`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(revoke.status).toBe(409)
  })

  it("邀请端点权限：member 403、未登录 401", async () => {
    const app = createApp()
    const { owner, member } = await setupOwnerMember(app, "inv-perm")
    const base = `/api/v1/orgs/${owner.org.id}/invitations`
    expect(
      (await request(app).get(base).set("Authorization", `Bearer ${member.accessToken}`)).status,
    ).toBe(403)
    expect((await request(app).get(base)).status).toBe(401)
  })
})
