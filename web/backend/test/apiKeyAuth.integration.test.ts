/**
 * 验证标准 #4：API Key 吊销后摄取鉴权立即失败。
 *
 * 用最小 Express app 挂载 requireApiKey（与 7d 摄取路由同款中间件），
 * 用 crypto 辅助函数按 §6.3 算法签名请求，验证：
 *  - 正确签名通过；
 *  - 错误 secret 被拒（AUTH_INVALID）；
 *  - 吊销后同一签名立即失败（AUTH_INVALID）。
 */

import express from "express"
import request from "supertest"

import { createApp } from "../src/server"
import { getPrisma } from "../src/infra/prisma"
import { requireApiKey } from "../src/middleware/apiKeyAuth"
import { errorHandler } from "../src/middleware/errorHandler"
import { registerUser, createProject, issueKey, signedPost } from "./helpers"

const prisma = getPrisma()

/** 与生产摄取路由同款的鉴权组装（7d 将复用 requireApiKey）。 */
function ingestionApp(): express.Application {
  const app = express()
  app.use(
    express.json({
      verify: (req, _res, buf) => {
        ;(req as express.Request).rawBody = buf
      },
    }),
  )
  app.post("/api/public/ingest", requireApiKey, (_req, res) =>
    res.status(202).json({ accepted: 0, duplicates: 0, errors: [] }),
  )
  app.use(errorHandler)
  return app
}

let setup: Awaited<ReturnType<typeof registerUser>>
let ingestion: express.Application
let key: Awaited<ReturnType<typeof issueKey>>
let projectId: string

beforeAll(async () => {
  const mgmt = createApp() // 管理 API（注册/建项目/签发 Key）
  setup = await registerUser(mgmt, "hk")
  const project = await createProject(mgmt, setup)
  projectId = project.id
  key = await issueKey(mgmt, { accessToken: setup.accessToken, projectId: project.id })
  ingestion = ingestionApp()
})

describe("#4 API Key HMAC 鉴权与吊销", () => {
  const url = "/api/public/ingest"
  const payload = { schema_version: "1.0", events: [] }

  it("accepts a correctly signed request (202)", async () => {
    const r = await signedPost(ingestion, {
      url,
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: payload,
    })
    expect(r.status).toBe(202)
  })

  it("rejects a wrong-signature request (401 AUTH_INVALID)", async () => {
    const r = await signedPost(ingestion, {
      url,
      secretKey: "sk-eval-wrongsecret",
      publicKey: key.publicKey,
      bodyObj: payload,
    })
    expect(r.status).toBe(401)
    expect(r.body.code).toBe("AUTH_INVALID")
  })

  it("rejects an unsigned request (401 AUTH_INVALID)", async () => {
    const r = await request(ingestion).post(url).type("json").send(JSON.stringify(payload))
    expect(r.status).toBe(401)
  })

  it("after revocation, the same signature is rejected immediately (401)", async () => {
    const mgmt = createApp()
    const revoke = await request(mgmt)
      .post(`/api/v1/projects/${projectId}/keys/${key.id}/revoke`)
      .set("Authorization", `Bearer ${setup.accessToken}`)
    expect(revoke.status).toBe(200)

    const row = await prisma.apiKey.findUnique({ where: { id: key.id } })
    expect(row!.revokedAt).not.toBeNull()

    const r = await signedPost(ingestion, {
      url,
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: payload,
    })
    expect(r.status).toBe(401)
    expect(r.body.code).toBe("AUTH_INVALID")
  })
})
