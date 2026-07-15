/**
 * 提示词结构化编辑表单（P4-3）。
 * 分屏编辑（System/User Prompt）+ Jinja2 变量检测 + 渲染预览。
 */
import { useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/shadcn/card"
import { Badge } from "../../../components/shadcn/badge"
import { Input } from "../../../components/shadcn/input"
import { Label } from "../../../components/shadcn/label"
import { Textarea } from "../../../components/shadcn/textarea"
import { Eye } from "lucide-react"

export interface PromptData {
  template_id: string
  name: string
  namespace?: string
  system_prompt: string
  user_prompt_template: string
  temperature?: number
  seed?: number
  num_samples?: number
  dimensions?: { dim_id: string; name: string; weight: number; score_range?: [number, number] }[]
}

/** 从模板提取 {{ var }} 变量名 */
function extractVars(template: string): string[] {
  const matches = template.match(/\{\{\s*(\w+)/g) ?? []
  return [...new Set(matches.map((m) => m.replace(/\{\{\s*/, "")))]
}

/** 简易 Jinja2 渲染（替换 {{ var }} 为 mock 值） */
function renderTemplate(template: string, vars: Record<string, string>): string {
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, key) => vars[key] ?? `{{ ${key} }}`)
}

export function PromptForm({
  data,
  onChange,
}: {
  data: PromptData
  onChange: (d: PromptData) => void
}) {
  const [activeTab, setActiveTab] = useState<"system" | "user">("system")
  const [mockVars, setMockVars] = useState<Record<string, string>>({})

  const vars = useMemo(() => extractVars(data.user_prompt_template), [data.user_prompt_template])
  const rendered = useMemo(
    () => renderTemplate(data.user_prompt_template, mockVars),
    [data.user_prompt_template, mockVars],
  )

  const update = (patch: Partial<PromptData>) => onChange({ ...data, ...patch })

  return (
    <div className="space-y-4">
      {/* 元数据 */}
      <Card>
        <CardContent className="grid grid-cols-3 gap-3 p-4">
          <div><Label>template_id</Label><Input className="font-mono text-xs" value={data.template_id} onChange={(e) => update({ template_id: e.target.value })} /></div>
          <div><Label>名称</Label><Input value={data.name} onChange={(e) => update({ name: e.target.value })} /></div>
          <div><Label>命名空间</Label><Input value={data.namespace ?? ""} onChange={(e) => update({ namespace: e.target.value })} /></div>
          <div><Label>temperature</Label><Input type="number" step="0.1" value={data.temperature ?? 0} onChange={(e) => update({ temperature: parseFloat(e.target.value) || 0 })} /></div>
          <div><Label>seed</Label><Input type="number" value={data.seed ?? 0} onChange={(e) => update({ seed: parseInt(e.target.value) || 0 })} /></div>
          <div><Label>num_samples</Label><Input type="number" value={data.num_samples ?? 1} onChange={(e) => update({ num_samples: parseInt(e.target.value) || 1 })} /></div>
        </CardContent>
      </Card>

      {/* 分屏：编辑 + 预览 */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* 左：编辑 */}
        <Card>
          <CardHeader className="flex-row items-center justify-between pb-2">
            <div className="flex gap-1">
              <button onClick={() => setActiveTab("system")} className={`rounded-md px-3 py-1 text-sm transition-colors ${activeTab === "system" ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground"}`}>System Prompt</button>
              <button onClick={() => setActiveTab("user")} className={`rounded-md px-3 py-1 text-sm transition-colors ${activeTab === "user" ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground"}`}>User Template</button>
            </div>
            {activeTab === "user" && vars.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {vars.map((v) => <Badge key={v} variant="outline" className="font-mono text-[10px] text-blue-400">{`{{ ${v} }}`}</Badge>)}
              </div>
            )}
          </CardHeader>
          <CardContent>
            {activeTab === "system" ? (
              <Textarea className="min-h-[300px] font-mono text-xs leading-relaxed" value={data.system_prompt} onChange={(e) => update({ system_prompt: e.target.value })} placeholder="System Prompt..." />
            ) : (
              <Textarea className="min-h-[300px] font-mono text-xs leading-relaxed" value={data.user_prompt_template} onChange={(e) => update({ user_prompt_template: e.target.value })} placeholder="User Prompt Template（Jinja2）..." />
            )}
          </CardContent>
        </Card>

        {/* 右：渲染预览 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-1.5 text-sm"><Eye className="size-3.5" /> 渲染预览</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* 变量填入 */}
            {vars.length > 0 && (
              <div className="space-y-1 rounded-md bg-muted/30 p-2">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">变量 Mock 值</p>
                {vars.map((v) => (
                  <div key={v} className="flex items-center gap-2">
                    <span className="w-20 shrink-0 font-mono text-[10px] text-blue-400">{`{{ ${v} }}`}</span>
                    <Input className="h-7 text-xs" placeholder={`mock value for ${v}`} value={mockVars[v] ?? ""} onChange={(e) => setMockVars({ ...mockVars, [v]: e.target.value })} />
                  </div>
                ))}
              </div>
            )}
            {/* System Prompt 预览 */}
            {activeTab === "system" && (
              <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap rounded-md bg-muted/20 p-3 font-mono text-xs leading-relaxed text-muted-foreground">{data.system_prompt || "(空)"}</pre>
            )}
            {/* User Template 渲染 */}
            {activeTab === "user" && (
              <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap rounded-md bg-muted/20 p-3 font-mono text-xs leading-relaxed text-muted-foreground">{rendered || "(空)"}</pre>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 评分维度（output_schema） */}
      {data.dimensions && data.dimensions.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">评分维度（output_schema）</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-1">
              {data.dimensions.map((dim, i) => (
                <div key={i} className="flex items-center gap-3 border-t py-2 text-sm first:border-t-0">
                  <span className="w-28 shrink-0 font-mono text-xs text-muted-foreground">{dim.dim_id}</span>
                  <span className="flex-1">{dim.name}</span>
                  <span className="text-xs text-muted-foreground">w={dim.weight}</span>
                  {dim.score_range && <span className="text-xs text-muted-foreground">[{dim.score_range.join(", ")}]</span>}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
