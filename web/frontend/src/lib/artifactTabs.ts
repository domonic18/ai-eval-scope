/**
 * 样本视图 tab 解析链（docs/arch/09 §9.7 呈现配置链前端半环）。
 *
 * 配置优先：场景 sample_view 配置存在 → tab 集/顺序/doc 命名按配置（组空的 tab 仍隐藏，
 * 防御旧数据；配置外的制品回落到 trace（未启用则 doc），保证无制品被隐藏）。
 * 配置缺失 → 机械兜底：kind=transcript 制品存在 ⇔ agent 会话形态（evaluator 仅 agent
 * 执行上传 transcript.md）→ agent 形态首 tab「Agent 回答」、task.json 归位「原始问题」；
 * 否则课件形态「原始文档」，task.json 落 trace，不再误显「原始问题」。
 * 词表是代码级固定词汇（同 metric id 性质），场景配置只做选择 / 排序 / 命名。
 */

import type { ArtifactRow, SampleViewConfig, SampleViewTab } from "@/types"

export type PrevTab = SampleViewTab

/** tab 缺省命名（config.labels 仅开放 doc 覆盖）。 */
export const TAB_LABELS: Record<SampleViewTab, string> = {
  doc: "原始文档",
  task: "原始问题",
  transcript: "对话过程",
  shot: "渲染截图",
  trace: "执行 Trace",
}

const VOCAB: SampleViewTab[] = ["doc", "task", "transcript", "shot", "trace"]

/** 制品 → tab 的机械分类（呈现配置无关）。isAgentSession 决定 task.json 归属。 */
export function artifactTab(
  a: Pick<ArtifactRow, "kind" | "contentType" | "originalName">,
  isAgentSession: boolean,
): SampleViewTab {
  if (a.kind === "transcript") return "transcript"
  if (a.originalName === "task.json") return isAgentSession ? "task" : "trace"
  if (a.kind === "trace" || a.contentType.includes("json") || a.kind === "judge_record")
    return "trace"
  if (a.contentType.startsWith("image") || a.kind === "screenshot") return "shot"
  return "doc"
}

export interface ResolvedTab {
  key: SampleViewTab
  label: string
  artifacts: ArtifactRow[]
}

/**
 * 解析样本视图：返回有序可见 tab（组空隐藏）。
 * 顺序 = 配置序（无配置 → 词表优先级 doc > task > transcript > shot > trace）。
 */
export function resolveTabs(
  artifacts: ArtifactRow[],
  opts: { config?: SampleViewConfig | null; isMultimodal?: boolean } = {},
): ResolvedTab[] {
  const isAgentSession = artifacts.some((a) => a.kind === "transcript")

  // 1. 机械分组
  const groups: Record<SampleViewTab, ArtifactRow[]> = { doc: [], task: [], transcript: [], shot: [], trace: [] }
  for (const a of artifacts) groups[artifactTab(a, isAgentSession)].push(a)

  // 2. 可见 tab 集与顺序：配置存在按配置；缺失走形态兜底（组空的档位剔除）
  let order: SampleViewTab[]
  if (opts.config?.tabs?.length) {
    order = opts.config.tabs.filter((t) => VOCAB.includes(t))
  } else {
    order = ["doc"]
    if (groups.task.length) order.push("task")
    if (groups.transcript.length) order.push("transcript")
    if (opts.isMultimodal) order.push("shot")
    order.push("trace")
  }

  // 3. 配置外桶的制品回落：trace 在配置内 → 并入 trace；否则并入 doc——不隐藏任何制品
  const enabled = new Set(order)
  const sink: SampleViewTab | null = enabled.has("trace") ? "trace" : enabled.has("doc") ? "doc" : null
  if (sink) {
    for (const t of VOCAB) {
      if (!enabled.has(t)) groups[sink].push(...groups[t])
    }
  }

  // 4. 命名：doc 可被配置覆盖；agent 形态首档为「Agent 回答」
  const docLabel = opts.config?.labels?.doc?.trim() || (isAgentSession ? "Agent 回答" : TAB_LABELS.doc)

  return order
    .map((key) => ({
      key,
      label: key === "doc" ? docLabel : TAB_LABELS[key],
      artifacts: groups[key],
    }))
    .filter((t) => t.artifacts.length > 0)
}
