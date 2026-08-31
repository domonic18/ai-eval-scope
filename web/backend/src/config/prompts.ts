/**
 * 配置资产 AI 生成提示词加载器（assets/prompts/ai.yaml）。
 *
 * prompt 不 hardcode 在代码里（对齐 evaluator assets/configs 惯例）；
 * 启动后首次访问加载并缓存，资产缺失/结构不完整 fail-fast（500）。
 * user_template 支持 {{ var }} 占位（renderTemplate 运行时替换）；
 * system 段不做渲染——其中 {{ content }} 等为提示词工程变量语法的字面量。
 */
import { readFileSync } from "fs"
import path from "path"
import yaml from "js-yaml"

export interface AiPromptPair {
  system: string
  userTemplate: string
}

const PROMPT_KEYS = ["optimize_prompt", "recommend_rules", "generate_metrics", "generate_policy"] as const
export type AiPromptKey = (typeof PROMPT_KEYS)[number]

const PROMPTS_PATH = path.resolve(__dirname, "../../assets/prompts/ai.yaml")

let _cache: Record<AiPromptKey, AiPromptPair> | null = null

export function loadAiPrompts(): Record<AiPromptKey, AiPromptPair> {
  if (_cache) return _cache
  let data: unknown
  try {
    data = yaml.load(readFileSync(PROMPTS_PATH, "utf-8"))
  } catch (e) {
    throw new Error(`AI 提示词资产损坏: ${PROMPTS_PATH}（${(e as Error).message}）`)
  }
  const out = {} as Record<AiPromptKey, AiPromptPair>
  if (typeof data !== "object" || data === null) {
    throw new Error(`AI 提示词资产结构无效: ${PROMPTS_PATH}`)
  }
  const source = data as Record<string, unknown>
  for (const key of PROMPT_KEYS) {
    const entry = source[key]
    if (
      typeof entry !== "object" ||
      entry === null ||
      typeof (entry as Record<string, unknown>).system !== "string" ||
      typeof (entry as Record<string, unknown>).user_template !== "string"
    ) {
      throw new Error(`AI 提示词资产缺 ${key}.system/user_template: ${PROMPTS_PATH}`)
    }
    out[key] = {
      system: (entry as Record<string, string>).system,
      userTemplate: (entry as Record<string, string>).user_template,
    }
  }
  _cache = out
  return out
}

/** {{ var }} 占位替换（未提供的变量替换为空串）。 */
export function renderTemplate(tpl: string, vars: Record<string, string>): string {
  return tpl.replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, key: string) => vars[key] ?? "")
}
