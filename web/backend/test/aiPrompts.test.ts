/** AI 生成提示词资产化测试：assets/prompts/ai.yaml 结构完整、模板渲染、端点组装（mock LLM）。 */

import { beforeEach, describe, expect, it, vi } from "vitest"

// vi.hoisted：mock 工厂被提升执行时仍可引用（避免 TDZ）
const { chatMock, findByIdMock } = vi.hoisted(() => ({
  chatMock: vi.fn(),
  findByIdMock: vi.fn(),
}))

vi.mock("../src/repositories/user.repository", () => ({
  UserRepository: class {
    findById = findByIdMock
  },
  OrgRepository: class {},
}))
vi.mock("../src/services/llm-client.service", () => ({
  llmClientService: {
    chat: (opts: unknown) => chatMock(opts),
  },
}))

import request from "supertest"
import { createApp } from "../src/server"
import { issueAccessTokenResult } from "../src/infra/crypto"
import { loadAiPrompts, renderTemplate } from "../src/config/prompts"

const adminToken = () =>
  issueAccessTokenResult({ userId: "u-admin", platformAdmin: true }).access_token

describe("assets/prompts/ai.yaml（结构完整性）", () => {
  it("四组提示词均含 system 与 user_template，特征句在位", () => {
    const prompts = loadAiPrompts()
    expect(prompts.optimize_prompt.system).toContain("提示词工程师")
    expect(prompts.recommend_rules.system).toContain("评估规则设计专家")
    expect(prompts.generate_metrics.system).toContain("评估指标设计专家")
    expect(prompts.generate_policy.system).toContain("stage_weights")
    for (const pair of Object.values(prompts)) {
      expect(pair.system.length).toBeGreaterThan(50)
      expect(pair.userTemplate).toMatch(/\{\{/)
    }
  })

  it("renderTemplate 替换占位；未提供的变量置空", () => {
    expect(renderTemplate("A: {{ a }}\nB: {{b}}", { a: "x" })).toBe("A: x\nB: ")
  })
})

describe("POST /api/v1/ai/optimize-prompt（提示词来自 YAML 资产）", () => {
  beforeEach(() => {
    chatMock.mockReset()
    findByIdMock.mockReset()
  })

  it("system 直用资产（{{ content }} 字面量不渲染）、user 渲染变量", async () => {
    findByIdMock.mockResolvedValue({ id: "u-admin", role: "admin", status: "active" })
    chatMock.mockResolvedValue('{"system":"s1","userPrompt":"u1"}')

    const app = createApp()
    const r = await request(app)
      .post("/api/v1/ai/optimize-prompt")
      .set("Authorization", `Bearer ${adminToken()}`)
      .send({ instruction: "优化数学评估", scenario: "courseware", currentSystem: "旧 system" })

    expect(r.status).toBe(200)
    expect(r.body).toEqual({ system: "s1", userPrompt: "u1" })

    const messages = (chatMock.mock.calls[0][0] as { messages: Array<{ role: string; content: string }> })
      .messages
    // system 来自 YAML：特征句 + 提示词工程变量语法的字面量保留
    expect(messages[0].content).toContain("提示词工程师")
    expect(messages[0].content).toContain("{{ content }}")
    // user 占位已渲染为实值
    expect(messages[1].content).toContain("评估场景：courseware")
    expect(messages[1].content).toContain("优化数学评估")
    expect(messages[1].content).toContain("参考（现有提示词，可改进）")
    expect(messages[1].content).not.toContain("{{")
  })

  it("无平台管理员权限 403", async () => {
    findByIdMock.mockResolvedValue(null)
    const app = createApp()
    const r = await request(app)
      .post("/api/v1/ai/optimize-prompt")
      .set("Authorization", `Bearer ${adminToken()}`)
      .send({ instruction: "x" })
    expect(r.status).toBe(403)
  })
})
