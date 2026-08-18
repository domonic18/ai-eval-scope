/**
 * jsonRepair 工具单测 — 纯函数，覆盖正常/代码块/截断/空输入等边界。
 */
import { describe, it, expect } from "vitest"
import { extractJson, repairTruncatedJson } from "../src/utils/jsonRepair"
import { PlatformError } from "../src/middleware/errorHandler"

describe("extractJson", () => {
  it("直接解析合法 JSON", () => {
    expect(extractJson('{"a":1}')).toEqual({ a: 1 })
    expect(extractJson("[1,2,3]")).toEqual([1, 2, 3])
  })

  it("剥离 ```json 代码块", () => {
    expect(extractJson('```json\n{"a":1}\n```')).toEqual({ a: 1 })
    expect(extractJson('```\n[1,2]\n```')).toEqual([1, 2])
  })

  it("从混合文本中抽取首个 JSON 对象", () => {
    expect(extractJson('好的，结果如下：\n{"system":"s","userPrompt":"u"}\n以上。')).toEqual({
      system: "s",
      userPrompt: "u",
    })
  })

  it("截断 JSON — 补全未闭合括号与引号", () => {
    // 模拟 LLM 输出被 max_tokens 截断
    const truncated = '{"system":"你是一位评'
    const result = extractJson(truncated) as { system: string }
    expect(result.system).toContain("你是一位评")
  })

  it("截断 JSON — 数组场景", () => {
    const truncated = '{"rules":[{"name":"规则1","method":"llm"},{"name":"规则2'
    const result = extractJson(truncated) as { rules: unknown[] }
    expect(result.rules.length).toBe(2)
  })

  it("空输入 → AI_EMPTY 502", () => {
    expect(() => extractJson("")).toThrow(PlatformError)
    try {
      extractJson("")
    } catch (e) {
      expect((e as PlatformError).status).toBe(502)
      expect((e as PlatformError).code).toBe("AI_EMPTY")
    }
  })

  it("非 JSON 文本 → AI_BAD_JSON 502", () => {
    expect(() => extractJson("这不是 JSON")).toThrow(PlatformError)
    try {
      extractJson("这不是 JSON")
    } catch (e) {
      expect((e as PlatformError).status).toBe(502)
      expect((e as PlatformError).code).toBe("AI_BAD_JSON")
    }
  })
})

describe("repairTruncatedJson", () => {
  it("补全奇数引号", () => {
    const repaired = repairTruncatedJson('{"key":"val')
    expect(() => JSON.parse(repaired)).not.toThrow()
  })

  it("补全未闭合大括号", () => {
    const repaired = repairTruncatedJson('{"a":1,"b":2')
    expect(JSON.parse(repaired)).toEqual({ a: 1, b: 2 })
  })

  it("补全嵌套结构", () => {
    const repaired = repairTruncatedJson('{"outer":{"inner":"val')
    expect(() => JSON.parse(repaired)).not.toThrow()
  })

  it("移除尾部悬挂逗号", () => {
    const repaired = repairTruncatedJson('{"a":1,')
    expect(JSON.parse(repaired)).toEqual({ a: 1 })
  })
})
