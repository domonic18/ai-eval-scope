/**
 * 规则集结构化编辑表单（P4-2）。
 * 表单 ↔ YAML 双向切换；维度/级联/规则卡片增删改。
 */
import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/shadcn/card"
import { Badge } from "../../../components/shadcn/badge"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Label } from "../../../components/shadcn/label"
import { Textarea } from "../../../components/shadcn/textarea"
import { Plus, Trash2, ChevronRight } from "lucide-react"

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

const TIERS: Record<string, { label: string; color: string }> = {
  format: { label: "HARD_GATE", color: "bg-red-500/15 text-red-400" },
  commonsense: { label: "HARD_SCORE", color: "bg-orange-500/15 text-orange-400" },
  soft: { label: "SOFT", color: "bg-yellow-500/15 text-yellow-400" },
  pref: { label: "PREFERENCE", color: "bg-blue-500/15 text-blue-400" },
}

export function RuleSetForm({
  data,
  onChange,
}: {
  data: RuleSetData
  onChange: (d: RuleSetData) => void
}) {
  const update = (patch: Partial<RuleSetData>) => onChange({ ...data, ...patch })

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

      {/* 维度 */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm">维度（{data.dimensions.length}）</CardTitle>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              维度是规则的分类标签，用于按类别汇总得分。如「功能性」「效果性」。
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={() => update({ dimensions: [...data.dimensions, { id: "", name: "", weight: 1 }] })}><Plus className="mr-1 size-3" />添加</Button>
        </CardHeader>
        <CardContent className="space-y-2">
          {data.dimensions.map((dim, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input className="w-32 font-mono text-xs" placeholder="英文标识 如 functional" value={dim.id} onChange={(e) => { const d = [...data.dimensions]; d[i] = { ...dim, id: e.target.value }; update({ dimensions: d }) }} />
              <Input className="flex-1" placeholder="展示名称 如 功能性" value={dim.name} onChange={(e) => { const d = [...data.dimensions]; d[i] = { ...dim, name: e.target.value }; update({ dimensions: d }) }} />
              <Input className="w-20" type="number" step="0.1" value={dim.weight} onChange={(e) => { const d = [...data.dimensions]; d[i] = { ...dim, weight: parseFloat(e.target.value) || 0 }; update({ dimensions: d }) }} />
              <Button size="sm" variant="ghost" className="text-red-400" onClick={() => update({ dimensions: data.dimensions.filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></Button>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* 级联阶段 */}
      <Card>
        <CardHeader><CardTitle className="text-sm">级联阶段（{data.cascade.length}）</CardTitle></CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-2">
            {data.cascade.map((c, i) => (
              <div key={i} className="flex items-center gap-2">
                {i > 0 && <ChevronRight className="size-4 text-muted-foreground" />}
                <div className={`rounded-md border px-3 py-1.5 text-sm ${c.stop_on_fail ? "border-red-500/40 text-red-400" : "border-border"}`}>
                  <span>{c.name || c.stage}</span>
                  <label className="ml-2 inline-flex items-center gap-1 text-[10px]">
                    <input type="checkbox" checked={c.stop_on_fail} onChange={(e) => { const cs = [...data.cascade]; cs[i] = { ...c, stop_on_fail: e.target.checked }; update({ cascade: cs }) }} />
                    短路
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
            <CardTitle className="text-sm">规则（{data.rules.length}）</CardTitle>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              每条规则绑定一个评估器（决定评估方式），归属于一个维度和级联阶段。
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={() => update({ rules: [...data.rules, { id: "", name: "", dimension: "", stage: "", evaluator: "", weight: 1 }] })}><Plus className="mr-1 size-3" />添加</Button>
        </CardHeader>
        <CardContent className="space-y-2">
          {data.rules.map((rule, i) => {
            const tierKey = rule.evaluator?.split(".")[0] ?? ""
            const tier = TIERS[tierKey]
            return (
              <div key={i} className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2">
                  <Input className="w-28 font-mono text-xs" placeholder="规则ID 如 FMT_001" value={rule.id} onChange={(e) => { const r = [...data.rules]; r[i] = { ...rule, id: e.target.value }; update({ rules: r }) }} />
                  <Input className="flex-1" placeholder="规则描述 如 输出格式有效" value={rule.name} onChange={(e) => { const r = [...data.rules]; r[i] = { ...rule, name: e.target.value }; update({ rules: r }) }} />
                  {tier && <Badge className={`shrink-0 text-[10px] ${tier.color}`}>{tier.label}</Badge>}
                  <Button size="sm" variant="ghost" className="text-red-400" onClick={() => update({ rules: data.rules.filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></Button>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <select className="rounded-md border bg-background px-2 py-1 text-xs" value={rule.dimension} onChange={(e) => { const r = [...data.rules]; r[i] = { ...rule, dimension: e.target.value }; update({ rules: r }) }}>
                    <option value="">所属维度</option>
                    {data.dimensions.map((d) => <option key={d.id} value={d.id}>{d.id}（{d.name}）</option>)}
                  </select>
                  <select className="rounded-md border bg-background px-2 py-1 text-xs" value={rule.stage} onChange={(e) => { const r = [...data.rules]; r[i] = { ...rule, stage: e.target.value }; update({ rules: r }) }}>
                    <option value="">所属阶段</option>
                    {data.cascade.map((c) => <option key={c.stage} value={c.stage}>{c.stage}</option>)}
                  </select>
                  <Input className="flex-1 font-mono text-xs" placeholder="evaluator" value={rule.evaluator} onChange={(e) => { const r = [...data.rules]; r[i] = { ...rule, evaluator: e.target.value }; update({ rules: r }) }} />
                  <Input className="w-16" type="number" step="0.1" value={rule.weight} onChange={(e) => { const r = [...data.rules]; r[i] = { ...rule, weight: parseFloat(e.target.value) || 0 }; update({ rules: r }) }} />
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>
    </div>
  )
}
