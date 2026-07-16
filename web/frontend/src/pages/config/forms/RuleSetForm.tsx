/**
 * 规则集结构化编辑表单（简化版）。
 *
 * 去掉独立的维度编辑区（维度是规则的分类标签，自动从规则推导）。
 * 规则卡片改为引导式填写：检查内容 → 阶段 → 评估方式（含类型指示）。
 */
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/shadcn/card"
import { Badge } from "../../../components/shadcn/badge"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Label } from "../../../components/shadcn/label"
import { ChevronRight, Plus, Trash2 } from "lucide-react"

export interface RuleSetData {
  version: string
  scenario: string
  description: string
  dimensions: { id: string; name: string; weight: number }[]
  cascade: { stage: string; name: string; stop_on_fail: boolean }[]
  rules: RuleItem[]
}
interface RuleItem {
  id: string
  name: string
  dimension: string
  stage: string
  evaluator: string
  weight: number
  description?: string
  enabled?: boolean
}

const EVALUATOR_PRESETS = [
  { id: "format.response_format", label: "格式检查（Markdown/HTML）", type: "🔧", group: "format" },
  { id: "format.html_validity", label: "HTML 有效性检查", type: "🔧", group: "format" },
  { id: "commonsense.info_accuracy", label: "知识准确性（正则+LLM）", type: "🔬", group: "commonsense" },
  { id: "commonsense.chronological_order", label: "时序正确性（LLM）", type: "🤖", group: "commonsense" },
  { id: "commonsense.logical_consistency", label: "逻辑一致性（LLM）", type: "🤖", group: "commonsense" },
  { id: "soft.teaching_logic", label: "教学逻辑（LLM Judge）", type: "🤖", group: "soft" },
  { id: "soft.content_diversity", label: "内容多样性（LLM Judge）", type: "🤖", group: "soft" },
  { id: "pref.style_preference", label: "风格偏好（LLM Judge）", type: "🤖", group: "pref" },
  { id: "pref.depth_preference", label: "深度偏好（LLM Judge）", type: "🤖", group: "pref" },
  { id: "pref.request_fulfillment", label: "需求满足度（LLM Judge）", type: "🤖", group: "pref" },
  { id: "vision.quality", label: "视觉质量（截图 LLM）", type: "📸", group: "vision" },
  { id: "custom", label: "自定义评估器…", type: "⚙️", group: "custom" },
]

const TYPE_HINTS: Record<string, string> = {
  "🔧": "规则检查：自动校验，无需 LLM",
  "🤖": "LLM 评分：需要配置提示词",
  "🔬": "混合验证：正则规则 + LLM 确认",
  "📸": "视觉评估：截图 + LLM 判断",
  "⚙️": "自定义评估器 ID",
}

function autoId(name: string, index: number): string {
  if (!name) return ""
  const prefix = name.slice(0, 3).toUpperCase().replace(/[^A-Z]/g, "")
  return `${prefix || "R"}_${String(index + 1).padStart(3, "0")}`
}

export function RuleSetForm({
  data,
  onChange,
}: {
  data: RuleSetData
  onChange: (d: RuleSetData) => void
}) {
  const update = (patch: Partial<RuleSetData>) => onChange({ ...data, ...patch })

  const addRule = () => {
    const idx = data.rules.length
    update({
      rules: [...data.rules, { id: "", name: "", dimension: "functional", stage: data.cascade[0]?.stage ?? "", evaluator: "", weight: 1 }],
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

  return (
    <div className="space-y-4">
      {/* 基本信息 */}
      <Card>
        <CardHeader><CardTitle className="text-sm">基本信息</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-3">
          <div><Label>版本</Label><Input value={data.version} onChange={(e) => update({ version: e.target.value })} /></div>
          <div><Label>场景</Label><Input value={data.scenario} onChange={(e) => update({ scenario: e.target.value })} /></div>
          <div className="col-span-2"><Label>描述</Label><Input value={data.description} onChange={(e) => update({ description: e.target.value })} /></div>
        </CardContent>
      </Card>

      {/* 级联阶段 */}
      <Card>
        <CardHeader><CardTitle className="text-sm">级联阶段</CardTitle></CardHeader>
        <CardContent>
          <p className="mb-3 text-[11px] text-muted-foreground">
            阶段决定评估顺序，门控阶段失败会短路后续。规则必须归属某个阶段。
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {data.cascade.map((c, i) => (
              <div key={i} className="flex items-center gap-2">
                {i > 0 && <ChevronRight className="size-4 text-muted-foreground" />}
                <div className={`rounded-md border px-3 py-1.5 text-sm ${c.stop_on_fail ? "border-red-500/40 text-red-400" : "border-border"}`}>
                  <span>{c.name || c.stage}</span>
                  <label className="ml-2 inline-flex items-center gap-1 text-[10px]">
                    <input type="checkbox" checked={c.stop_on_fail} onChange={(e) => { const cs = [...data.cascade]; cs[i] = { ...c, stop_on_fail: e.target.checked }; update({ cascade: cs }) }} />
                    失败短路
                  </label>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 规则 */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm">规则（{data.rules.length} 条）</CardTitle>
          </div>
          <Button size="sm" variant="outline" onClick={addRule}><Plus className="mr-1 size-3" />添加规则</Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.rules.map((rule, i) => {
            const preset = EVALUATOR_PRESETS.find((p) => p.id === rule.evaluator)
            const typeIcon = preset?.type ?? (rule.evaluator ? "⚙️" : "")
            return (
              <div key={i} className="rounded-md border border-border p-3">
                {/* 第一行：你要检查什么 */}
                <div className="flex items-start gap-2">
                  <div className="flex-1">
                    <Label className="text-[11px] text-muted-foreground">检查内容</Label>
                    <Input
                      placeholder="如：格式是否有效 / 行程安全检查 / 教学逻辑"
                      value={rule.name}
                      onChange={(e) => updateRule(i, { name: e.target.value })}
                    />
                  </div>
                  {typeIcon && (
                    <Badge className="mt-5 shrink-0 text-[10px]" title={TYPE_HINTS[typeIcon]}>{typeIcon}</Badge>
                  )}
                  <Button size="sm" variant="ghost" className="mt-5 text-red-400" onClick={() => update({ rules: data.rules.filter((_, j) => j !== i) })}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>

                {/* 第二行：在哪个阶段 + 用什么方式 */}
                <div className="mt-2 flex flex-wrap items-end gap-2">
                  <div className="min-w-[120px]">
                    <Label className="text-[11px] text-muted-foreground">所属阶段</Label>
                    <select
                      className="w-full rounded-md border bg-background px-2 py-2 text-xs"
                      value={rule.stage}
                      onChange={(e) => updateRule(i, { stage: e.target.value })}
                    >
                      <option value="">选择阶段…</option>
                      {data.cascade.map((c) => (
                        <option key={c.stage} value={c.stage}>{c.name || c.stage}{c.stop_on_fail ? "（门控）" : ""}</option>
                      ))}
                    </select>
                  </div>
                  <div className="min-w-[180px] flex-1">
                    <Label className="text-[11px] text-muted-foreground">评估方式</Label>
                    <select
                      className="w-full rounded-md border bg-background px-2 py-2 text-xs"
                      value={rule.evaluator}
                      onChange={(e) => updateRule(i, { evaluator: e.target.value === "custom" ? "" : e.target.value })}
                    >
                      <option value="">选择评估方式…</option>
                      {EVALUATOR_PRESETS.map((p) => (
                        <option key={p.id} value={p.id}>{p.type} {p.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* 评估方式提示 */}
                {preset && (
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    {TYPE_HINTS[preset.type]}
                    {preset.type === "🤖" && " — 需要在「提示词」中配置对应的 system/user prompt"}
                  </p>
                )}
                {!preset && rule.evaluator && (
                  <Input className="mt-1.5 font-mono text-xs" placeholder="自定义 evaluator ID（如 my.checker）" value={rule.evaluator} onChange={(e) => updateRule(i, { evaluator: e.target.value })} />
                )}
              </div>
            )
          })}
          {data.rules.length === 0 && (
            <p className="py-4 text-center text-sm text-muted-foreground">还没有规则，点击「添加规则」开始</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
