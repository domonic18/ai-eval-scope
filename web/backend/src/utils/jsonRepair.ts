/**
 * JSON 修复与抽取工具（从 routes/ai.ts 提取）。
 *
 * 处理 LLM 返回的 JSON：容忍 ```json 代码块包裹、max_tokens 截断导致的
 * 不完整 JSON（补全未闭合字符串与括号）。
 */
import { PlatformError } from "../middleware/errorHandler"

/** 尝试修复被 max_tokens 截断的 JSON：补全未闭合的字符串与括号。
 *  仅作尽力修复（best-effort），失败则由调用方抛出友好错误。 */
export function repairTruncatedJson(s: string): string {
  let out = s
  // 闭合未配对的字符串（行内出现的奇数个双引号）
  const dq = (out.match(/(?<!\\)"/g) ?? []).length
  if (dq % 2 === 1) out += '"'
  // 统计未闭合的括号并补全
  const stack: string[] = []
  let inStr = false
  let escape = false
  for (const ch of out) {
    if (escape) {
      escape = false
      continue
    }
    if (ch === "\\") {
      escape = true
      continue
    }
    if (ch === '"') {
      inStr = !inStr
      continue
    }
    if (inStr) continue
    if (ch === "{" || ch === "[") stack.push(ch)
    else if (ch === "}" || ch === "]") {
      const top = stack[stack.length - 1]
      if ((ch === "}" && top === "{") || (ch === "]" && top === "[")) stack.pop()
    }
  }
  // 移除尾部悬挂的逗号
  out = out.replace(/,\s*$/, "")
  while (stack.length) {
    const top = stack.pop()!
    out += top === "{" ? "}" : "]"
  }
  return out
}

/** 从 LLM 文本响应中抽取首个 JSON 对象/数组（容忍 ```json 代码块包裹与截断）。 */
export function extractJson(text: string): unknown {
  if (!text) throw new PlatformError("LLM 未返回内容", { status: 502, code: "AI_EMPTY" })
  const cleaned = text.replace(/```json\s*/gi, "").replace(/```\s*$/g, "").trim()
  // 直接解析
  try {
    return JSON.parse(cleaned)
  } catch {
    /* fall through */
  }
  // 抽取首个 {...} 或 [...] 起始
  const start = cleaned.search(/[[{]/)
  if (start < 0) throw new PlatformError("LLM 响应非合法 JSON", { status: 502, code: "AI_BAD_JSON" })
  const tail = cleaned.slice(start)
  // 尝试原样解析（找到最后闭合符）
  const open = cleaned[start]
  const close = open === "[" ? "]" : "}"
  const end = cleaned.lastIndexOf(close)
  if (end > start) {
    try {
      return JSON.parse(cleaned.slice(start, end + 1))
    } catch {
      /* fall through to repair */
    }
  }
  // 截断修复：补全未闭合字符串与括号
  try {
    return JSON.parse(repairTruncatedJson(tail))
  } catch {
    throw new PlatformError("LLM 响应 JSON 解析失败（可能输出被截断，请重试）", {
      status: 502,
      code: "AI_BAD_JSON",
    })
  }
}
