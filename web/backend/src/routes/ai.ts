/**
 * 配置资产 AI 生成路由（/api/v1/ai）—— 仅平台管理员可用（requireAuth + platformAdminGuard，docs/arch/13）。
 *
 * 复用 llmClientService.chat()（默认 LLM）。每个资产的结构化 prompt 维护在
 * assets/prompts/ai.yaml（不 hardcode，对齐项目 prompt-YAML 规范），
 * 要求 LLM 返回严格 JSON，后端解析校验后回传，前端再「采纳」写回编辑器。
 *
 * 入口对齐原型：prompt-editor ✨AI优化 / rule-set-editor ✨AI推荐规则 /
 * 指标定义 ✨AI生成 / 聚合策略 ✨AI生成（后两者为本次新增入口）。
 */
import { Router } from "express"
import { requireAuth } from "../middleware/auth"
import { platformAdminGuard } from "../middleware/adminGuard"
import { PlatformError } from "../middleware/errorHandler"
import { wrap } from "../middleware/wrap"
import { extractJson } from "../utils/jsonRepair"
import { llmClientService, type ChatMessage } from "../services/llm-client.service"
import { loadAiPrompts, renderTemplate } from "../config/prompts"

const router = Router()
router.use(requireAuth, platformAdminGuard)

/** 调用 LLM 并抽取 JSON。 */
async function chatJson(messages: ChatMessage[]): Promise<unknown> {
  const text = await llmClientService.chat({ messages, maxTokens: 4096 })
  return extractJson(text)
}

/* ── 提示词生成/优化（PromptForm ✨ AI 生成）────────── */
router.post(
  "/optimize-prompt",
  wrap(async (req, res) => {
    const { instruction, scenario, currentSystem, currentUserPrompt } = (req.body ?? {}) as {
      instruction?: string
      scenario?: string
      currentSystem?: string
      currentUserPrompt?: string
    }
    if (!instruction || !instruction.trim()) {
      throw new PlatformError("请先描述你希望提示词做什么 / 优化方向", { status: 400, code: "VALIDATION_ERROR" })
    }
    const prompt = loadAiPrompts().optimize_prompt
    const reference =
      currentSystem || currentUserPrompt
        ? `参考（现有提示词，可改进）：\nSystem: ${currentSystem || "(无)"}\nUser: ${currentUserPrompt || "(无)"}\n`
        : ""
    const messages: ChatMessage[] = [
      { role: "system", content: prompt.system },
      {
        role: "user",
        content: renderTemplate(prompt.userTemplate, {
          scenario: scenario || "通用",
          instruction,
          reference,
        }),
      },
    ]
    const result = (await chatJson(messages)) as { system?: string; userPrompt?: string }
    res.json({
      system: typeof result.system === "string" ? result.system : "",
      userPrompt: typeof result.userPrompt === "string" ? result.userPrompt : "",
    })
  }),
)

/* ── 规则推荐（RuleSetForm ✨ AI 推荐规则）────────── */
router.post(
  "/recommend-rules",
  wrap(async (req, res) => {
    const { scenario, cascade, existingRules } = (req.body ?? {}) as {
      scenario?: string
      cascade?: Array<{ stage: string; name?: string }>
      existingRules?: Array<{ name?: string; method?: string; stage?: string }>
    }
    const stages = (cascade ?? []).map((c) => `${c.stage}(${c.name ?? c.stage})`).join("、") || "未提供"
    const exist = (existingRules ?? []).map((r) => r.name).filter(Boolean).join("、") || "无"
    const prompt = loadAiPrompts().recommend_rules
    const messages: ChatMessage[] = [
      { role: "system", content: prompt.system },
      {
        role: "user",
        content: renderTemplate(prompt.userTemplate, {
          scenario: scenario || "通用",
          stages,
          existing: exist,
        }),
      },
    ]
    const result = (await chatJson(messages)) as { rules?: unknown }
    const rules = Array.isArray(result.rules) ? result.rules : []
    res.json({ rules })
  }),
)

/* ── 指标定义生成（MetricDefsEditor ✨ AI 生成）────── */
router.post(
  "/generate-metrics",
  wrap(async (req, res) => {
    const { scenario, description } = (req.body ?? {}) as { scenario?: string; description?: string }
    if (!description) throw new PlatformError("description 必填", { status: 400, code: "VALIDATION_ERROR" })
    const prompt = loadAiPrompts().generate_metrics
    const messages: ChatMessage[] = [
      { role: "system", content: prompt.system },
      {
        role: "user",
        content: renderTemplate(prompt.userTemplate, {
          scenario: scenario || "通用",
          description,
        }),
      },
    ]
    const result = (await chatJson(messages)) as { metricDefinitions?: unknown }
    const metricDefinitions = Array.isArray(result.metricDefinitions) ? result.metricDefinitions : []
    res.json({ metricDefinitions })
  }),
)

/* ── 聚合策略生成（AggregationPolicyEditor ✨ AI 生成） */
router.post(
  "/generate-policy",
  wrap(async (req, res) => {
    const { scenario, cascade, metricDefinitions } = (req.body ?? {}) as {
      scenario?: string
      cascade?: Array<{ stage: string; name?: string }>
      metricDefinitions?: Array<{ id?: string; name?: string; threshold?: number | null; unit?: string | null }>
    }
    const stages = (cascade ?? []).map((c) => `${c.stage}(${c.name ?? c.stage})`).join("、") || "未提供"
    const metricsBlock =
      metricDefinitions && metricDefinitions.length > 0
        ? metricDefinitions
            .map((m) => `- ${m.id ?? "?"}${m.name ? `（${m.name}）` : ""}${m.threshold != null ? `，阈值 ${m.threshold}` : ""}`)
            .join("\n")
        : "未提供"
    const prompt = loadAiPrompts().generate_policy
    const messages: ChatMessage[] = [
      { role: "system", content: prompt.system },
      {
        role: "user",
        content: renderTemplate(prompt.userTemplate, {
          scenario: scenario || "通用",
          stages,
          metricsBlock,
        }),
      },
    ]
    const result = (await chatJson(messages)) as { aggregationPolicy?: unknown }
    res.json({ aggregationPolicy: result.aggregationPolicy ?? null })
  }),
)

export default router
