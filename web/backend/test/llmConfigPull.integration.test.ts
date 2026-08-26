/** LLM③：/api/public/llm-config 执行面角色拉取集成测试（arch/16 §6.2-四 云端形态）。 */

import { afterEach, describe, expect, it } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { createProject, issueKey, registerUser } from "./helpers"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const MODEL_IDS: string[] = []
const ORG_IDS: string[] = []
const USER_EMAILS: string[] = []

afterEach(async () => {
  await prisma.llmModel.deleteMany({ where: { id: { in: MODEL_IDS } } }).catch(() => {})
  for (const id of ORG_IDS) await prisma.organization.deleteMany({ where: { id } }).catch(() => {})
  for (const email of USER_EMAILS) await prisma.user.deleteMany({ where: { email } }).catch(() => {})
  MODEL_IDS.length = 0
  ORG_IDS.length = 0
  USER_EMAILS.length = 0
})

/** 注册用户并提升 platform admin（llm-models 管理面仅平台超管可写）。 */
async function makeAdmin(app: ReturnType<typeof createApp>, prefix: string) {
  const u = await registerUser(app, prefix)
  USER_EMAILS.push(u.email)
  ORG_IDS.push(u.org.id)
  await prisma.user.update({ where: { email: u.email }, data: { role: "admin" } })
  return u
}

async function createModel(
  app: ReturnType<typeof createApp>,
  token: string,
  body: Record<string, unknown>,
) {
  const r = await request(app)
    .post("/api/v1/admin/llm-models")
    .set("Authorization", `Bearer ${token}`)
    .send(body)
  expect(r.status).toBe(201)
  MODEL_IDS.push(r.body.id)
  return r.body
}

describe("GET /api/public/llm-config", () => {
  it("按角色返回解密配置；同角色取 isDefault 优先；无鉴权 401；role 校验 400", async () => {
    const app = createApp()
    const admin = await makeAdmin(app, "llmcfg")

    // role 非法值 → 400
    const bad = await request(app)
      .post("/api/v1/admin/llm-models")
      .set("Authorization", `Bearer ${admin.accessToken}`)
      .send({ name: "Bad", provider: "openai", role: "other", modelName: "m", apiKey: "sk-x" })
    expect(bad.status).toBe(400)

    // text 默认行 + text 新行（isDefault 拉高优先）+ vision 行
    await createModel(app, admin.accessToken, {
      name: "Text New",
      provider: "openai",
      role: "text",
      modelName: "text-new",
      baseUrl: "https://t.example.com",
      apiKey: "sk-text-new",
    })
    await createModel(app, admin.accessToken, {
      name: "Text Default",
      provider: "openai",
      role: "text",
      modelName: "text-default",
      baseUrl: "https://t.example.com",
      apiKey: "sk-text-def",
      extra: { max_tokens: 1024 },
      isDefault: true,
    })
    await createModel(app, admin.accessToken, {
      name: "Vision",
      provider: "anthropic",
      role: "vision",
      modelName: "vision-model",
      baseUrl: "https://v.example.com",
      apiKey: "sk-vision",
    })

    const project = await createProject(app, admin)
    const key = await issueKey(app, { accessToken: admin.accessToken, projectId: project.id })

    const pull = await request(app)
      .get("/api/public/llm-config")
      .set("Authorization", `Bearer ${key.token}`)
    expect(pull.status).toBe(200)
    expect(Object.keys(pull.body.roles).sort()).toEqual(["text", "vision"])
    // 同角色 isDefault 优先（Default 后建但被拉高）
    expect(pull.body.roles.text.model).toBe("text-default")
    expect(pull.body.roles.text.api_key).toBe("sk-text-def")
    expect(pull.body.roles.text.max_tokens).toBe(1024)
    expect(pull.body.roles.vision).toMatchObject({
      provider: "anthropic",
      model: "vision-model",
      api_key: "sk-vision",
      base_url: "https://v.example.com",
    })

    const anon = await request(app).get("/api/public/llm-config")
    expect(anon.status).toBe(401)
  })
})
