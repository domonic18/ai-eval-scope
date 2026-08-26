/** W3：平台 Secrets（org 级 KV，写后不可读）+ /api/public/secrets 拉取集成测试。 */

import { afterEach, describe, expect, it } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { createProject, issueKey, registerUser } from "./helpers"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const ORG_IDS: string[] = []
const USER_EMAILS: string[] = []

function track(u: { email: string; org: { id: string } }) {
  USER_EMAILS.push(u.email)
  ORG_IDS.push(u.org.id)
}

afterEach(async () => {
  for (const id of ORG_IDS) await prisma.organization.deleteMany({ where: { id } }).catch(() => {})
  for (const email of USER_EMAILS) await prisma.user.deleteMany({ where: { email } }).catch(() => {})
  ORG_IDS.length = 0
  USER_EMAILS.length = 0
})

describe("平台 Secrets（/orgs/:org/secrets）", () => {
  it("owner 录入 → 列表不显值 → member 只读 → 非成员 404 → 删除", async () => {
    const app = createApp()
    const owner = await registerUser(app, "sec-own")
    track(owner)
    const base = `/api/v1/orgs/${owner.org.id}/secrets`

    const put = await request(app)
      .put(`${base}/SASAN__USERNAME`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ value: "138xxx" })
    expect(put.status).toBe(200)
    expect(put.body.name).toBe("SASAN__USERNAME")
    expect(JSON.stringify(put.body)).not.toContain("138xxx") // 值不回显

    const list = await request(app).get(base).set("Authorization", `Bearer ${owner.accessToken}`)
    expect(list.status).toBe(200)
    expect(list.body.secrets).toHaveLength(1)
    expect(list.body.secrets[0].name).toBe("SASAN__USERNAME")
    expect(JSON.stringify(list.body)).not.toContain("138xxx") // 写后不可读

    const member = await registerUser(app, "sec-mem")
    track(member)
    await request(app)
      .post(`/api/v1/orgs/${owner.org.id}/members`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ email: member.email })
    const memberPut = await request(app)
      .put(`${base}/SASAN__PASSWORD`)
      .set("Authorization", `Bearer ${member.accessToken}`)
      .send({ value: "x" })
    expect(memberPut.status).toBe(403) // member 只读
    const memberList = await request(app)
      .get(base)
      .set("Authorization", `Bearer ${member.accessToken}`)
    expect(memberList.status).toBe(200)

    const outsider = await registerUser(app, "sec-out")
    track(outsider)
    expect(
      (
        await request(app)
          .get(base)
          .set("Authorization", `Bearer ${outsider.accessToken}`)
      ).status,
    ).toBe(404)

    const del = await request(app)
      .delete(`${base}/SASAN__USERNAME`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
    expect(del.status).toBe(204)
  })

  it("非法名 400；未登录 401", async () => {
    const app = createApp()
    const owner = await registerUser(app, "sec-bad")
    track(owner)
    const base = `/api/v1/orgs/${owner.org.id}/secrets`
    const bad = await request(app)
      .put(`${base}/lower-case`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ value: "x" })
    expect(bad.status).toBe(400)
    expect((await request(app).get(base)).status).toBe(401)
  })
})

describe("GET /api/public/secrets（executor 拉取）", () => {
  it("API Key 鉴权拉取解密 KV；覆盖后拿到新值；无鉴权 401", async () => {
    const app = createApp()
    const owner = await registerUser(app, "sec-pull")
    track(owner)
    const base = `/api/v1/orgs/${owner.org.id}/secrets`
    await request(app)
      .put(`${base}/AGENT_EVAL_SUT__SASAN__USERNAME`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ value: "u-old" })
    await request(app)
      .put(`${base}/AGENT_EVAL_SUT__SASAN__PASSWORD`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ value: "p-old" })

    const project = await createProject(app, owner)
    const key = await issueKey(app, { accessToken: owner.accessToken, projectId: project.id })

    const pull = await request(app)
      .get("/api/public/secrets")
      .set("Authorization", `Bearer ${key.token}`)
    expect(pull.status).toBe(200)
    expect(pull.body.secrets).toEqual({
      AGENT_EVAL_SUT__SASAN__USERNAME: "u-old",
      AGENT_EVAL_SUT__SASAN__PASSWORD: "p-old",
    })

    // 覆盖 → 拉取新值
    await request(app)
      .put(`${base}/AGENT_EVAL_SUT__SASAN__USERNAME`)
      .set("Authorization", `Bearer ${owner.accessToken}`)
      .send({ value: "u-new" })
    const pull2 = await request(app)
      .get("/api/public/secrets")
      .set("Authorization", `Bearer ${key.token}`)
    expect(pull2.body.secrets.AGENT_EVAL_SUT__SASAN__USERNAME).toBe("u-new")

    expect((await request(app).get("/api/public/secrets")).status).toBe(401)
  })
})
