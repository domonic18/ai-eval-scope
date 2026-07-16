/**
 * 规则集结构化编辑表单。
 *
 * 基本信息 + 级联阶段（可增/删/改名）+ 规则列表（每条由 RuleCard 引导式填写）。
 * 评估方式改为 3 个场景无关通用项（LLM/视觉/规则集），不再硬编码课件专用评估器。
 */
import { useRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/shadcn/card"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { ChevronRight, Plus, X } from "lucide-react"
import type { CatalogEntry, DatasetCatalogEntry } from "../../../api/client"
import { RuleCard } from "./RuleCard"
import { Field } from "./Field"

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
  evaluator: string
  method?: EvalMethod // 评估方式（通用：llm / llm_vision / rule_set / format）
  promptId?: string // LLM/视觉方式绑定的提示词 asset_id
  datasetId?: string // 规则集方式绑定的参考数据集 asset_id
  formatType?: FormatCheckType // 格式检查方式：后缀/JSON/HTML/Markdown
  extensions?: string[] // formatType=extension 时的允许后缀列表
  weight: number
  description?: string
  enabled?: boolean
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
  onNewDataset,
}: {
  data: RuleSetData
  onChange: (d: RuleSetData) => void
  prompts?: CatalogEntry[]
  datasets?: DatasetCatalogEntry[]
  onNewPrompt?: () => void
  onNewDataset?: () => void
}) {
  const cascadeRef = useRef<HTMLDivElement>(null)
  const update = (patch: Partial<RuleSetData>) => onChange({ ...data, ...patch })

  const addRule = () => {
    update({
      rules: [
        ...data.rules,
        { id: "", name: "", dimension: "functional", stage: data.cascade[0]?.stage ?? "", evaluator: "", weight: 1 },
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

  // 级联阶段：增/删/改名/切换门控
  const addStage = () => {
    const n = data.cascade.length + 1
    update({ cascade: [...data.cascade, { stage: `stage_${n}`, name: "", stop_on_fail: false }] })
    // 滚动聚焦到级联卡片，便于立刻命名（规则卡片中"新建阶段"也会复用本函数）
    window.setTimeout(() => cascadeRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 30)
  }
  const updateStage = (i: number, patch: Partial<RuleSetData["cascade"][number]>) => {
    const cs = [...data.cascade]
    cs[i] = { ...cs[i], ...patch }
    update({ cascade: cs })
  }
  const removeStage = (i: number) => {
    const removed = data.cascade[i]
    if (!removed) return
    // 删除阶段并解除引用该阶段的规则（置空 stage，避免悬空）
    update({
      cascade: data.cascade.filter((_, j) => j !== i),
      rules: data.rules.map((r) => (r.stage === removed.stage ? { ...r, stage: "" } : r)),
    })
  }

  return (
    <div className="space-y-4">
      {/* 基本信息 */}
      <Card>
        <CardHeader><CardTitle className="text-sm">基本信息</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-3">
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
        </CardContent>
      </Card>

      {/* 级联阶段 */}
      <Card>
        <CardHeader><CardTitle className="text-sm">级联阶段</CardTitle></CardHeader>
        <CardContent>
          <div ref={cascadeRef} className="flex flex-wrap items-center gap-2">
            {data.cascade.length === 0 && (
              <p className="text-[11px] text-muted-foreground">还没有阶段，点下方「添加阶段」创建（如：格式校验 / 安全 / 质量）。</p>
            )}
            {data.cascade.map((c, i) => (
              <div key={i} className="flex items-center gap-2">
                {i > 0 && <ChevronRight className="size-4 text-muted-foreground" />}
                <div className={`flex items-center gap-1.5 rounded-md border px-2 py-1 ${c.stop_on_fail ? "border-red-500/40" : "border-border"}`}>
                  <Input
                    className="h-6 w-28 border-0 bg-transparent px-1 text-sm shadow-none focus-visible:ring-0"
                    placeholder={`阶段 ${i + 1}`}
                    value={c.name}
                    onChange={(e) => updateStage(i, { name: e.target.value })}
                  />
                  <label className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={c.stop_on_fail}
                      onChange={(e) => updateStage(i, { stop_on_fail: e.target.checked })}
                    />
                    失败短路
                  </label>
                  <button className="text-muted-foreground hover:text-red-400" title="删除阶段" onClick={() => removeStage(i)}>
                    <X className="size-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-muted-foreground">
            阶段决定评估顺序，门控阶段失败会短路后续；规则必须归属某个阶段。
          </p>
          <Button size="sm" variant="outline" className="mt-3" onClick={addStage}>
            <Plus className="mr-1 size-3" />添加阶段
          </Button>
        </CardContent>
      </Card>

      {/* 规则 */}
      <Card>
        <CardHeader><CardTitle className="text-sm">规则（{data.rules.length} 条）</CardTitle></CardHeader>
        <CardContent className="space-y-3">
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
              onNewPrompt={onNewPrompt}
              onNewDataset={onNewDataset}
            />
          ))}
          {data.rules.length === 0 && (
            <p className="py-4 text-center text-sm text-muted-foreground">还没有规则，点击下方「添加规则」开始</p>
          )}
          <Button size="sm" variant="outline" onClick={addRule}>
            <Plus className="mr-1 size-3" />添加规则
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
