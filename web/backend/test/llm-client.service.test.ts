/**
 * LLM 客户端服务单测 — mock 加密与仓储，stubGlobal fetch 隔离网络（禁联网纪律）。
 * 聚焦 testModel 的 role 分支：jev 判定专线走 Noul 决策端点探针，chat 角色走原协议。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"

const { decryptMock, recordTestMock } = vi.hoisted(() => ({
  decryptMock: vi.fn(),
  recordTestMock: vi.fn(),
}))

vi.mock("../src/infra/crypto", () => ({
  decryptToken: decryptMock,
  encryptToken: vi.fn(),
  maskToken: vi.fn(),
}))
vi.mock("../src/repositories/llm-model.repository", () => ({
  llmModelRepository: { recordTest: recordTestMock },
}))

import { llmClientService } from "../src/services/llm-client.service"
import type { LlmModel } from "@prisma/client"

/** 构造最小 LlmModel 行（仅 resolve/testModel 消费的字段，其余断言补齐）。 */
function fakeModel(overrides: Partial<Record<string, unknown>> = {}): LlmModel {
  return {
    id: "m1",
    role: "text",
    provider: "openai",
    baseUrl: "https://t.example.com",
    apiKeyEncrypted: "enc",
    modelName: "gpt-4",
    isActive: true,
    extra: null,
    ...overrides,
  } as LlmModel
}

const fetchMock = vi.fn()

beforeEach(() => {
  decryptMock.mockReset().mockReturnValue("sk-plain")
  recordTestMock.mockReset()
  fetchMock.mockReset()
  vi.stubGlobal("fetch", fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("testModel — role=jev 判定专线", () => {
  it("走 Noul 决策端点探针（/alpha/decisions），成功回显概率", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ answers: { connectivity: { noul: 0.87 } } }), { status: 200 }),
    )
    const r = await llmClientService.testModel(fakeModel({ role: "jev", modelName: "typesafe/jev-1.13" }))
    expect(r.status).toBe("success")
    expect(r.detail).toContain("Noul p=0.87")
    expect(recordTestMock).toHaveBeenCalledWith("m1", "success", null)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("https://t.example.com/alpha/decisions")
    expect(init.method).toBe("POST")
    expect(init.headers.authorization).toBe("Bearer sk-plain")
    const body = JSON.parse(init.body)
    expect(body.model).toBe("typesafe/jev-1.13")
    expect(body.questions.connectivity.type).toBe("noul")
  })

  it("响应缺 noul 概率字段 → failed（畸形响应不误报连通）", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ answers: {} }), { status: 200 }))
    const r = await llmClientService.testModel(fakeModel({ role: "jev" }))
    expect(r.status).toBe("failed")
    expect(r.detail).toContain("noul")
    expect(recordTestMock).toHaveBeenCalledWith("m1", "failed", expect.stringContaining("noul"))
  })

  it("HTTP 401 → failed 且 detail 带状态码（鉴权失效可见）", async () => {
    fetchMock.mockResolvedValue(new Response("unauthorized", { status: 401 }))
    const r = await llmClientService.testModel(fakeModel({ role: "jev" }))
    expect(r.status).toBe("failed")
    expect(r.detail).toContain("HTTP 401")
    expect(recordTestMock).toHaveBeenCalledWith("m1", "failed", expect.stringContaining("HTTP 401"))
  })
})

describe("testModel — chat 角色（text/vision/agent）", () => {
  it("openai 协议仍走 /chat/completions，不经 Noul 端点", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ choices: [{ message: { content: "pong" } }] }), { status: 200 }),
    )
    const r = await llmClientService.testModel(fakeModel({ role: "text" }))
    expect(r.status).toBe("success")
    expect(fetchMock.mock.calls[0][0]).toBe("https://t.example.com/chat/completions")
  })
})
