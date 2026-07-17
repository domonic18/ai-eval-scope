/**
 * 规则集结构化编辑表单。
 *
 * 基本信息 + 级联阶段（卡片流：可增/删/改 id+名/上下移动/门控开关）+ 规则列表（RuleCard 引导式）。
 * 评估方式为场景无关通用项（LLM/视觉/规则集/格式检查），不再硬编码课件专用评估器。
 */
import { useRef } from "react"
import { Input } from "../../../components/shadcn/input"
import { ChevronDown, ChevronRight, ChevronUp, ClipboardCheck, GripVertical, Info, TrendingUp, X } from "lucide-react"
import {
  AddButton,
  SectionCard,
  SectionCardContent,
  SectionCardHeader,
  SectionCardTitle,
} from "../../../components/shared"
import type { CatalogEntry, DatasetCatalogEntry } from "../../../api/client"
import { RuleCard } from "./RuleCard"
import { Field, Toggle } from "./Field"

export interface RuleSetData {
  version: string
  scenario: string
  description: string
  dimensions: { id: string; name: string; weight: number }[]
  cascade: { stage: string; name: string; stop_on_fail: boolean }[]
  rules: RuleItem[]
}
export type EvalMethod = "llm" | "llm_vision" | "rule_set" | "format"
// 格式/程序化检查类型（非 LLM、非 rule-base）
export type FormatCheckType = "extension" | "json_validity" | "html_validity" | "markdown"
export interface RuleItem {
  id: string
  name: string
  dimension: string
  stage: string
  method?: EvalMethod // 评估方式（通用：llm / llm_vision / rule_set / format）
  prompt_id?: string // LLM/视觉/复合评估的主提示词 asset_id
  confirmation_prompt_id?: string // rule_set 复合评估的二次确认提示词（如 fact_verdict）
  dataset_ids?: string[] // 规则集评估的参考数据集列表；空=全部参考数据集（知识库）
  format_type?: FormatCheckType // 格式检查方式：后缀/JSON/HTML/Markdown
  extensions?: string[] // format_type=extension 时的允许后缀列表
  evaluator?: string // 具体执行器标识；省略时由 method + 绑定资产派生
  weight: number
  description?: string
  enabled?: boolean
  params?: Record<string, unknown> // 执行器额外参数（保留给高级场景）
}

function autoId(name: string, index: number): string {
  if (!name) return ""
  const prefix = name.slice(0, 3).toUpperCase().replace(/[^A-Z]/g, "")
  return `${prefix || "R"}_${String(index + 1).padStart(3, "0")}`
}

export function RuleSetForm({
  data,
  onChange,
  prompts = [],
  datasets = [],
  onNewPrompt,
  onNewPromptForRule,
  onNewDataset,
  onJumpAsset,
}: {
  data: RuleSetData
  onChange: (d: RuleSetData) => void
  prompts?: CatalogEntry[]
  datasets?: DatasetCatalogEntry[]
  /** 旧入口：无规则上下文的新建（如顶部工具栏） */
  onNewPrompt?: () => void
  /** 按规则绑定的新建提示词：创建后自动写入指定规则的字段 */
  onNewPromptForRule?: (ruleIndex: number, field: "prompt_id" | "confirmation_prompt_id") => void
  onNewDataset?: () => void
  onJumpAsset?: (type: "prompt" | "dataset", assetId: string) => void
}) {
  const cascadeRef = useRef<HTMLDivElement>(null)
  const update = (patch: Partial<RuleSetData>) => onChange({ ...data, ...patch })

  const addRule = () => {
    update({
      rules: [
        ...data.rules,
        {
          id: "",
          name: "",
          dimension: "functional",
          stage: data.cascade[0]?.stage ?? "",
          method: undefined,
          weight: 1,
        },
      ],
    })
  }

  const updateRule = (i: number, patch: Partial<RuleItem>) => {
    const rules = [...data.rules]
    rules[i] = { ...rules[i], ...patch }
    // 自动生成 ID（如果用户没填）
    if (!rules[i].id && patch.name) {
      rules[i].id = autoId(patch.name, i)
    }
    update({ rules })
  }

  // 级联阶段：增/删/改/移动
  const addStage = () => {
    const n = data.cascade.length + 1
    update({ cascade: [...data.cascade, { stage: `stage_${n}`, name: "", stop_on_fail: false }] })
    window.setTimeout(() => cascadeRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 30)
  }
  const updateStage = (i: number, patch: Partial<RuleSetData["cascade"][number]>) => {
    const cs = [...data.cascade]
    const old = cs[i]
    cs[i] = { ...cs[i], ...patch }
    // 若改了 stage id，同步引用旧 id 的规则
    const rules =
      patch.stage !== undefined && patch.stage !== old.stage
        ? data.rules.map((r) => (r.stage === old.stage ? { ...r, stage: patch.stage as string } : r))
        : data.rules
    update({ cascade: cs, rules })
  }
  const moveStage = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= data.cascade.length) return
    const cs = [...data.cascade]
    ;[cs[i], cs[j]] = [cs[j], cs[i]]
    update({ cascade: cs })
  }
  const removeStage = (i: number) => {
    const removed = data.cascade[i]
    if (!removed) return
    update({
      cascade: data.cascade.filter((_, j) => j !== i),
      rules: data.rules.map((r) => (r.stage === removed.stage ? { ...r, stage: "" } : r)),
    })
  }

  return (
    <div className="space-y-4">
      {/* 基本信息 */}
      <SectionCard>
        <SectionCardHeader>
          <SectionCardTitle className="flex items-center gap-2">
            <Info className="size-4" /> 基本信息
          </SectionCardTitle>
        </SectionCardHeader>
        <SectionCardContent className="grid grid-cols-2 gap-3">
          <Field label="版本" required hint="语义化版本号，如 1.0.0">
            <Input value={data.version} onChange={(e) => update({ version: e.target.value })} />
          </Field>
          <Field label="场景" required hint="所属场景 id，决定资产归属与默认配置">
            <Input value={data.scenario} onChange={(e) => update({ scenario: e.target.value })} />
          </Field>
          <div className="col-span-2">
            <Field label="描述" optional hint="规则集用途与覆盖范围说明，便于他人理解">
              <Input value={data.description} onChange={(e) => update({ description: e.target.value })} />
            </Field>
          </div>
        </SectionCardContent>
      </SectionCard>

      {/* 级联阶段 */}
      <SectionCard>
        <SectionCardHeader>
          <SectionCardTitle className="flex items-center gap-2">
            <TrendingUp className="size-4" />
            级联阶段
            <span className="text-[11px] font-normal text-muted-foreground">cascade</span>
          </SectionCardTitle>
          <span className="text-[11px] text-muted-foreground">拖拽调整顺序 · 失败可短路</span>
        </SectionCardHeader>
        <SectionCardContent>
          <div ref={cascadeRef} className="flex flex-wrap items-stretch gap-2">
            {data.cascade.length === 0 && (
              <p className="text-[11px] text-muted-foreground">还没有阶段，点下方「添加阶段」创建（如：格式校验 / 安全 / 质量）。</p>
            )}
            {data.cascade.map((c, i) => (
              <div key={i} className="contents">
                {i > 0 && <ChevronRight className="self-center text-muted-foreground/30" />}
                <div
                  className={`relative flex min-w-[210px] flex-1 flex-col rounded-md border bg-secondary p-3.5 transition-all hover:-translate-y-0.5 hover:shadow-md hover:border-primary/40 ${c.stop_on_fail ? "border-destructive/30" : "border-border"}`}
                >
                  <div className="mb-3 flex items-center justify-between">
                    <GripVertical className="size-3.5 cursor-grab text-muted-foreground/40" />
                    <span className="rounded bg-card px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">#{i + 1}</span>
                  </div>
                  <div className="space-y-2">
                    <Input
                      className="h-7 font-mono text-xs"
                      placeholder="stage id"
                      value={c.stage}
                      onChange={(e) => updateStage(i, { stage: e.target.value })}
                    />
                    <Input
                      className="h-7 text-xs"
                      placeholder="显示名"
                      value={c.name}
                      onChange={(e) => updateStage(i, { name: e.target.value })}
                    />
                  </div>
                  <div className="mt-3 flex items-center justify-between">
                    <Toggle
                      checked={c.stop_on_fail}
                      onChange={(v) => updateStage(i, { stop_on_fail: v })}
                      label="失败短路"
                    />
                    <div className="flex items-center gap-0.5 text-muted-foreground">
                      <button type="button" title="上移" disabled={i === 0} onClick={() => moveStage(i, -1)} className="rounded p-1 hover:bg-accent hover:text-foreground disabled:opacity-30"><ChevronUp className="size-3.5" /></button>
                      <button type="button" title="下移" disabled={i === data.cascade.length - 1} onClick={() => moveStage(i, 1)} className="rounded p-1 hover:bg-accent hover:text-foreground disabled:opacity-30"><ChevronDown className="size-3.5" /></button>
                      <button type="button" title="删除阶段" onClick={() => removeStage(i)} className="rounded p-1 hover:bg-destructive/10 hover:text-destructive"><X className="size-3.5" /></button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-muted-foreground">
            阶段决定评估顺序，门控阶段失败会短路后续；规则必须归属某个阶段。
          </p>
          <AddButton onClick={addStage}>添加阶段</AddButton>
        </SectionCardContent>
      </SectionCard>

      {/* 规则 */}
      <SectionCard>
        <SectionCardHeader>
          <SectionCardTitle className="flex items-center gap-2">
            <ClipboardCheck className="size-4" />
            规则
            <span className="text-[11px] font-normal text-muted-foreground">{data.rules.length} 条</span>
          </SectionCardTitle>
        </SectionCardHeader>
        <SectionCardContent className="space-y-3">
          {data.rules.map((rule, i) => (
            <RuleCard
              key={i}
              rule={rule}
              cascade={data.cascade}
              prompts={prompts}
              datasets={datasets}
              onUpdate={(patch) => updateRule(i, patch)}
              onDelete={() => update({ rules: data.rules.filter((_, j) => j !== i) })}
              onNewStage={addStage}
              onNewPrompt={
                onNewPromptForRule
                  ? () => onNewPromptForRule(i, "prompt_id")
                  : onNewPrompt
              }
              onNewConfirmationPrompt={
                onNewPromptForRule
                  ? () => onNewPromptForRule(i, "confirmation_prompt_id")
                  : undefined
              }
              onNewDataset={onNewDataset}
              onJumpAsset={onJumpAsset}
            />
          ))}
          {data.rules.length === 0 && (
            <p className="py-4 text-center text-sm text-muted-foreground">还没有规则，点击下方「添加规则」开始</p>
          )}
          <AddButton onClick={addRule}>添加规则</AddButton>
        </SectionCardContent>
      </SectionCard>
    </div>
  )
}
