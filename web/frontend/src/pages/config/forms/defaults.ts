/**
 * 配置表单的「新建空白内容」工厂与预置骨架。
 * 独立成文件，避免与表单组件同文件导出（触发 react-refresh/only-export-components）。
 */
import type { PromptData } from "./PromptForm"
import type { DatasetData } from "./DatasetForm"

/** 新建提示词的默认 System Prompt 骨架（用户可改） */
const DEFAULT_SYSTEM_PROMPT = `你是一位严谨、客观的评估专家，负责对「被测系统输出」按既定标准打分。

评估原则：
1. 仅依据下方评判标准打分，不掺杂个人偏好与外部知识；
2. 逐条核对标准，未满足即扣分，并在理由中明确指出；
3. 输出必须是合法 JSON：{"score": <0-100 的整数>, "reason": "<扣分/得分理由>"}。

请保持稳定、可复现的判断。`

/** 新建提示词的默认 User Prompt 模板骨架（含 {{ content }} 变量，用户可改） */
const DEFAULT_USER_PROMPT_TEMPLATE = `请评估以下输出。

【被测输出】
{{ content }}

【评判标准】
- （在此填写本维度具体标准，如：事实正确、逻辑连贯、格式合规）

【输出要求】
仅返回 JSON：{"score": <0-100>, "reason": "<理由>"}`

/** 新建提示词时的空白内容（预置默认 system/user 骨架） */
export function createEmptyPrompt(assetId: string): PromptData {
  return {
    template_id: assetId,
    name: "",
    namespace: "",
    system_prompt: DEFAULT_SYSTEM_PROMPT,
    user_prompt_template: DEFAULT_USER_PROMPT_TEMPLATE,
    temperature: 0.2,
    seed: 42,
    num_samples: 1,
    dimensions: [],
  }
}

/** 新建数据集时的空白内容（默认 reference 角色） */
export function createEmptyDataset(): DatasetData {
  return { subject: "", description: "", version: "1.0", role: "reference", constants: [], misconceptions: [] }
}

/** 新建规则集时的最小骨架（docs/arch/14 配置编辑器交互设计 §6.4 补「新建规则集」死路） */
export function createEmptyRuleSet(_assetId: string, scenarioId: string): Record<string, unknown> {
  return {
    version: "0.1.0",
    scenario: scenarioId,
    description: "",
    dimensions: [{ id: "functional", name: "功能性", weight: 1.0 }],
    cascade: [{ stage: "stage_1", name: "", stop_on_fail: false }],
    rules: [],
  }
}
