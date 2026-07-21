/**
 * LLM 客户端服务（docs/arch/15）。
 *
 * 协议分支裸 HTTP：openai 走 /chat/completions，anthropic 走 /v1/messages。
 * - testModel(id): 1-token ping，返回 {status, detail}（失败也为 200，body 字段），写回 last_test_*。
 * - chat({messages, modelId?}): 通用 chat 入口，供 /api/v1/ai/* 生成功能复用。
 *
 * 不引入 SDK 依赖，仅用全局 fetch（Node 18+）。
 */
import type { LlmModel } from "@prisma/client"
import { decryptToken } from "../infra/crypto"
import { llmModelRepository } from "../repositories/llm-model.repository"
import { PlatformError } from "../middleware/errorHandler"

export interface ChatMessage {
  role: "system" | "user" | "assistant"
  content: string
}

export interface TestResult {
  status: "success" | "failed"
  detail: string
  testedAt: string
}

/** chat（生成内容）用长超时；连通性测试用短超时（见 testModel）。 */
const CHAT_TIMEOUT_MS = 120000
const TEST_TIMEOUT_MS = 30000
const ANTHROPIC_VERSION = "2023-06-01"

/** 协议默认 base_url（未填时）。 */
const DEFAULT_BASE: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com",
}

function resolveKey(model: LlmModel): string {
  try {
    return decryptToken(model.apiKeyEncrypted)
  } catch {
    throw new PlatformError("api_key 解密失败，请重新填写", { status: 500, code: "LLM_KEY_DECRYPT" })
  }
}

function normalizeBase(provider: string, baseUrl: string | null): string {
  const b = (baseUrl || DEFAULT_BASE[provider] || "").replace(/\/+$/, "")
  if (!b) throw new PlatformError(`provider=${provider} 缺少 base_url`, { status: 400, code: "LLM_NO_BASEURL" })
  return b
}

interface ResolvedModel {
  provider: string
  baseUrl: string
  apiKey: string
  modelName: string
  extra: Record<string, unknown>
}

function resolve(model: LlmModel): ResolvedModel {
  return {
    provider: model.provider,
    baseUrl: normalizeBase(model.provider, model.baseUrl),
    apiKey: resolveKey(model),
    modelName: model.modelName,
    extra: (model.extra as Record<string, unknown>) ?? {},
  }
}

/** openai 协议：POST {base}/chat/completions。 */
async function chatOpenai(m: ResolvedModel, messages: ChatMessage[], maxTokens: number, timeoutMs = CHAT_TIMEOUT_MS): Promise<string> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    authorization: `Bearer ${m.apiKey}`,
  }
  const body: Record<string, unknown> = {
    model: m.modelName,
    messages,
    max_tokens: maxTokens,
  }
  if (typeof m.extra.temperature === "number") body.temperature = m.extra.temperature
  const resp = await fetch(`${m.baseUrl}/chat/completions`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (!resp.ok) throw new LlmHttpError(resp.status, await safeText(resp))
  const data = (await resp.json()) as { choices?: Array<{ message?: { content?: string } }> }
  return data.choices?.[0]?.message?.content ?? ""
}

/** anthropic 协议：POST {base}/v1/messages。 */
async function chatAnthropic(m: ResolvedModel, messages: ChatMessage[], maxTokens: number, timeoutMs = CHAT_TIMEOUT_MS): Promise<string> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "x-api-key": m.apiKey,
    "anthropic-version": ANTHROPIC_VERSION,
  }
  // anthropic system 为顶层字段，messages 不含 system
  const system = messages.find((x) => x.role === "system")?.content
  const msgs = messages.filter((x) => x.role !== "system").map((x) => ({ role: x.role, content: x.content }))
  const body: Record<string, unknown> = {
    model: m.modelName,
    max_tokens: maxTokens,
    messages: msgs,
  }
  if (system) body.system = system
  if (typeof m.extra.temperature === "number") body.temperature = m.extra.temperature
  const resp = await fetch(`${m.baseUrl}/v1/messages`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (!resp.ok) throw new LlmHttpError(resp.status, await safeText(resp))
  const data = (await resp.json()) as { content?: Array<{ type: string; text?: string }> }
  return (data.content ?? []).filter((c) => c.type === "text").map((c) => c.text ?? "").join("")
}

class LlmHttpError extends Error {
  status: number
  body: string
  constructor(status: number, body: string) {
    super(`HTTP ${status}`)
    this.name = "LlmHttpError"
    this.status = status
    this.body = body
  }
}

async function safeText(resp: Response): Promise<string> {
  try {
    return await resp.text()
  } catch {
    return ""
  }
}

class LlmClientService {
  /** 通用 chat：默认/指定模型 → 文本。供 AI 生成功能复用。 */
  async chat(opts: { messages: ChatMessage[]; modelId?: string; maxTokens?: number }): Promise<string> {
    const model = opts.modelId
      ? await llmModelRepository.getRaw(opts.modelId)
      : await llmModelRepository.getDefaultRaw()
    if (!model || !model.isActive) {
      throw new PlatformError("未配置可用的默认 LLM 模型，请联系管理员在后台配置", {
        status: 503,
        code: "LLM_NOT_CONFIGURED",
      })
    }
    const m = resolve(model)
    const maxTokens = opts.maxTokens ?? Number(m.extra.max_tokens ?? 2048)
    try {
      if (m.provider === "anthropic") return await chatAnthropic(m, opts.messages, maxTokens)
      return await chatOpenai(m, opts.messages, maxTokens)
    } catch (e) {
      if ((e as Error)?.name === "TimeoutError" || /timeout|aborted/i.test((e as Error).message)) {
        throw new PlatformError("LLM 调用超时（模型响应过慢或输出过长），请重试或在后台减小 max_tokens", {
          status: 504,
          code: "LLM_TIMEOUT",
        })
      }
      // 上游 LLM HTTP 错误（401/429/500…）不应泄漏给客户端 → 包装为 502
      if (e instanceof LlmHttpError) {
        throw new PlatformError(`LLM 上游错误（HTTP ${e.status}）`, {
          status: 502,
          code: "LLM_UPSTREAM",
          details: { upstreamStatus: e.status, body: e.body.slice(0, 200) },
        })
      }
      throw e
    }
  }

  /** 连通性测试：1-token ping，返回成功/失败（失败也为 HTTP 200，body 字段）。 */
  async testModel(model: LlmModel): Promise<TestResult> {
    const testedAt = new Date().toISOString()
    try {
      const m = resolve(model)
      const ping: ChatMessage[] = [{ role: "user", content: "ping" }]
      if (m.provider === "anthropic") await chatAnthropic(m, ping, 1, TEST_TIMEOUT_MS)
      else await chatOpenai(m, ping, 1, TEST_TIMEOUT_MS)
      await llmModelRepository.recordTest(model.id, "success", null)
      return { status: "success", detail: `模型 ${model.modelName} 连通正常`, testedAt }
    } catch (e) {
      const detail = e instanceof LlmHttpError ? `HTTP ${e.status}: ${e.body.slice(0, 200)}` : (e as Error).message
      await llmModelRepository.recordTest(model.id, "failed", detail)
      return { status: "failed", detail, testedAt }
    }
  }

  /** 导出 llm_config.yaml 文本（key 用 ${ENV_VAR} 占位），供 evaluator 同步。 */
  async exportYaml(): Promise<string> {
    const rows = await (await import("../infra/prisma")).getPrisma().llmModel.findMany({
      where: { isActive: true },
      orderBy: [{ isDefault: "desc" }, { createdAt: "desc" }],
    })
    if (rows.length === 0) throw new PlatformError("无可用模型", { status: 404, code: "LLM_NONE" })
    const def = rows.find((r) => r.isDefault) ?? rows[0]
    const envHint: string[] = []
    const providers = rows
      .map((r) => {
        const env = `${r.name.toUpperCase().replace(/[^A-Z0-9]+/g, "_")}_API_KEY`
        envHint.push(`${env}=`)
        const extra = (r.extra as Record<string, unknown>) ?? {}
        const lines = [
          `      provider: ${r.provider === "openai" ? "openai" : "anthropic"}`,
          `      model: ${r.modelName}`,
          `      api_key: \${${env}}`,
          r.baseUrl ? `      base_url: ${r.baseUrl}` : null,
          typeof extra.max_tokens === "number" ? `      max_tokens: ${extra.max_tokens}` : null,
          typeof extra.temperature === "number" ? `      temperature: ${extra.temperature}` : null,
        ]
          .filter(Boolean)
          .join("\n")
        return `    ${slug(r.name)}:\n${lines}`
      })
      .join("\n")
    return `# 由 Web 后台导出 — 覆盖 evaluator/agent_eval/assets/configs/llm_config.yaml
# 需在 evaluator/.env 配置以下变量：
# ${envHint.join("\n# ")}
llm:
  default: ${slug(def.name)}
  providers:
${providers}
`
  }
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "provider"
}

export const llmClientService = new LlmClientService()
