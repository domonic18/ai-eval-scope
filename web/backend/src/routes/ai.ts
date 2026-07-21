/**
 * 配置资产 AI 生成路由（/api/v1/ai）—— 所有登录用户可用（requireAuth）。
 *
 * 复用 llmClientService.chat()（默认 LLM）。每个端点内置该资产的结构化 prompt，
 * 要求 LLM 返回严格 JSON，后端解析校验后回传，前端再「采纳」写回编辑器。
 *
 * 入口对齐原型：prompt-editor ✨AI优化 / rule-set-editor ✨AI推荐规则 /
 * 指标定义 ✨AI生成 / 聚合策略 ✨AI生成（后两者为本次新增入口）。
 */
import { Router } from "express"
import { requireAuth } from "../middleware/auth"
import { PlatformError } from "../middleware/errorHandler"
import { wrap } from "../middleware/wrap"
import { extractJson } from "../utils/jsonRepair"
import { llmClientService, type ChatMessage } from "../services/llm-client.service"

const router = Router()
router.use(requireAuth)

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
    const messages: ChatMessage[] = [
      {
        role: "system",
        content:
          '你是一位资深 LLM 评估提示词工程师。根据用户的需求描述（意图），生成一套严谨、可复现的评估提示词（System + User Prompt Template）。\n' +
          "硬约束：\n" +
          "1. 输出语言必须是**简体中文**（变量名 {{ }}、JSON 字段名、英文专有名词除外）；\n" +
          "2. User Prompt Template 需用 {{ content }} / {{ title }} 等变量引用被评估内容；\n" +
          "3. 明确输出格式约束（如要求 JSON 评分输出）；\n" +
          '4. 严格只返回 JSON：{"system": string, "userPrompt": string}。',
      },
      {
        role: "user",
        content:
          `评估场景：${scenario || "通用"}\n\n` +
          `我的需求描述（请据此生成/优化提示词）：\n${instruction}\n\n` +
          (currentSystem || currentUserPrompt
            ? `参考（现有提示词，可改进）：\nSystem: ${currentSystem || "(无)"}\nUser: ${currentUserPrompt || "(无)"}\n`
            : "") +
          `\n请用简体中文输出 JSON。`,
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
    const messages: ChatMessage[] = [
      {
        role: "system",
        content:
          '你是评估规则设计专家。基于评估场景与级联阶段，推荐 3-5 条可补全的规则。所有文本字段（name/description）必须用**简体中文**。每条规则字段：name(检查内容), method(llm|llm_vision|rule_set|format), stage(必须从给定阶段选), description。严格只返回 JSON：{"rules": [...]}。',
      },
      {
        role: "user",
        content: `评估场景：${scenario || "通用"}\n级联阶段：${stages}\n已有规则：${exist}\n\n请推荐补充规则（JSON）。`,
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
    const messages: ChatMessage[] = [
      {
        role: "system",
        content:
          '你是评估指标设计专家。基于评估目标，设计可量化的指标定义。所有文本字段（name/summary）必须用**简体中文**（id/expression 保持英文标识符）。每项字段：id(小写snake), name(中文), summary(一句话大白话描述指标含义，给非技术用户看，如"所有样本的格式是否合规"), expression(可计算表达式), threshold(0-1 数值或 null), unit(ratio|score|count|ms)。严格只返回 JSON：{"metricDefinitions": [...]}。',
      },
      {
        role: "user",
        content: `评估场景：${scenario || "通用"}\n评估目标描述：${description}\n\n请生成指标定义（JSON）。`,
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
    const messages: ChatMessage[] = [
      {
        role: "system",
        content:
          "你是评估聚合策略设计专家。聚合策略（AggregationPolicy）通过 stage_weights 把各**级联阶段**的评估结果加权聚合出样本级 Reward；指标定义（MetricDefinition）则从 Reward 等字段派生运行级指标。\n" +
          "你的任务：基于给定的**级联阶段**与**指标定义**，设计 stage_weights，使各阶段权重与指标反映的评估重点一致（指标多/阈值严的阶段权重更高；门控类阶段设 is_gate=true）。\n" +
          "约束：\n" +
          "1. 若给定了级联阶段，stage_id 必须**严格取自**该列表；\n" +
          "2. 若未给定级联阶段，则根据指标定义推断合理的评估阶段（如格式门控 format、内容校验 content、质量评估 quality 等），stage_id 用 snake_case 英文，并据此生成 stage_weights——**不得返回空数组**；\n" +
          "3. 所有 stage_weights 的 weight 之和应归一（建议和为 1.0，门控阶段可不计入或小权重）；\n" +
          "4. 所有文本说明用**简体中文**；\n" +
          '5. 严格只返回 JSON：{"aggregationPolicy": {"stage_weights": [{"stage_id": string, "weight": number, "is_gate": boolean}]}}。',
      },
      {
        role: "user",
        content:
          `评估场景：${scenario || "通用"}\n` +
          `级联阶段：${stages}\n` +
          `已定义指标（据此判断各阶段重要性）：\n${metricsBlock}\n\n` +
          `请生成聚合策略（JSON）。`,
      },
    ]
    const result = (await chatJson(messages)) as { aggregationPolicy?: unknown }
    res.json({ aggregationPolicy: result.aggregationPolicy ?? null })
  }),
)

export default router
