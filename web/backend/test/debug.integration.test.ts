/**
 * 调试台 /api/v1/debug 鉴权语义回归。
 *
 * 核心回归点：api_key 验签失败必须 403 API_KEY_INVALID，**不得 401**——
 * 前端 axios 拦截器（web/frontend/src/api/client.ts）把一切非 /auth/ 的 401
 * 视为会话过期并强制登出，回 401 会让"调试台 Key 填错"表现成"掉登录"。
 * JWT 会话失败仍保持 401（该登出）。
 */

import request from "supertest"

import { createApp } from "../src/server"
import { registerUser, createProject, issueKey } from "./helpers"

let setup: Awaited<ReturnType<typeof registerUser>>
let key: Awaited<ReturnType<typeof issueKey>>

beforeAll(async () => {
  const app = createApp()
  setup = await registerUser(app, "dbg")
  const project = await createProject(app, setup)
  key = await issueKey(app, { accessToken: setup.accessToken, projectId: project.id })
})

/** 携带 JWT 会话的调试台提交（api_key 走 query，正文为原始字节）。 */
function submit(apiKey?: string) {
  const req = request(createApp())
    .post("/api/v1/debug/jobs")
    .set("Authorization", `Bearer ${setup.accessToken}`)
    .set("Content-Type", "application/octet-stream")
    .query({ filename: "lesson.md", rule_set_id: "coursework-quality" })
    .send(Buffer.from("# hello debug"))
  return apiKey ? req.query({ api_key: apiKey }) : req
}

describe("POST /api/v1/debug/jobs 鉴权语义", () => {
  it("无 JWT 会话 → 401（会话失效该登出）", async () => {
    const r = await request(createApp())
      .post("/api/v1/debug/jobs")
      .set("Content-Type", "application/octet-stream")
      .query({ filename: "lesson.md", api_key: key.token })
      .send(Buffer.from("# x"))
    expect(r.status).toBe(401)
    expect(r.body.code).toBe("AUTH_INVALID")
  })

  it("缺 api_key → 400 INPUT_INVALID", async () => {
    const r = await submit()
    expect(r.status).toBe(400)
    expect(r.body.code).toBe("INPUT_INVALID")
  })

  it("无效 api_key → 403 API_KEY_INVALID（回归锁：不得 401，否则前端误登出）", async () => {
    const r = await submit("eval-not-a-real-key")
    expect(r.status).toBe(403)
    expect(r.status).not.toBe(401)
    expect(r.body.code).toBe("API_KEY_INVALID")
  })

  it("有效 api_key → 202 入队", async () => {
    const r = await submit(key.token)
    expect(r.status).toBe(202)
    expect(r.body.job_id).toBeTruthy()
    expect(r.body.status).toBe("queued")
  })

  it("已吊销 api_key → 403 API_KEY_INVALID", async () => {
    const app = createApp()
    const project = await createProject(app, setup)
    const tmp = await issueKey(app, { accessToken: setup.accessToken, projectId: project.id })
    const revoke = await request(app)
      .post(`/api/v1/projects/${project.id}/keys/${tmp.id}/revoke`)
      .set("Authorization", `Bearer ${setup.accessToken}`)
      .send()
    expect(revoke.status).toBe(200)

    const r = await submit(tmp.token)
    expect(r.status).toBe(403)
    expect(r.body.code).toBe("API_KEY_INVALID")
  })
})
