/**
 * 提示词结构化编辑表单（P4-3）。
 * System / User Prompt 上下布局（行业通行，非横向 Tab）+ Jinja2 变量检测 + 渲染预览。
 * 新建提示词时由 createEmptyPrompt() 预置默认骨架内容，便于用户填写修改。
 */
import { useMemo, useState } from "react"
import { Badge } from "../../../components/shadcn/badge"
import { Input } from "../../../components/shadcn/input"
import { Textarea } from "../../../components/shadcn/textarea"
import { Eye } from "lucide-react"
import { SectionCard, SectionCardContent, SectionCardHeader, SectionCardTitle } from "../../../components/shared"
import { Field } from "./Field"

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
  const [mockVars, setMockVars] = useState<Record<string, string>>({})

  const vars = useMemo(() => extractVars(data.user_prompt_template), [data.user_prompt_template])
  const rendered = useMemo(
    () => renderTemplate(data.user_prompt_template, mockVars),
    [data.user_prompt_template, mockVars],
  )

  const update = (patch: Partial<PromptData>) => onChange({ ...data, ...patch })

  return (
    <div className="space-y-4">
      {/* 基本信息 */}
      <SectionCard>
        <SectionCardContent className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3">
          <Field label="template_id" required hint="唯一标识，包内不可重复，如 safety_check">
            <Input className="font-mono text-xs" value={data.template_id} onChange={(e) => update({ template_id: e.target.value })} />
          </Field>
          <Field label="名称" required hint="人类可读名称，如：安全合规检查">
            <Input value={data.name} onChange={(e) => update({ name: e.target.value })} />
          </Field>
          <Field label="命名空间" optional hint="资产隔离命名空间，留空则默认 default">
            <Input value={data.namespace ?? ""} onChange={(e) => update({ namespace: e.target.value })} />
          </Field>
          <Field label="temperature" optional hint="采样温度，0 近乎确定，值越大越发散">
            <Input type="number" step="0.1" value={data.temperature ?? 0} onChange={(e) => update({ temperature: parseFloat(e.target.value) || 0 })} />
          </Field>
          <Field label="seed" optional hint="随机种子，固定种子可使结果可复现">
            <Input type="number" value={data.seed ?? 0} onChange={(e) => update({ seed: parseInt(e.target.value) || 0 })} />
          </Field>
          <Field label="num_samples" optional hint="每个输入的采样次数（多次取聚合）">
            <Input type="number" value={data.num_samples ?? 1} onChange={(e) => update({ num_samples: parseInt(e.target.value) || 1 })} />
          </Field>
        </SectionCardContent>
      </SectionCard>

      {/* System Prompt（上下布局，始终可见） */}
      <SectionCard>
        <SectionCardHeader className="pb-2">
          <SectionCardTitle className="text-sm">System Prompt</SectionCardTitle>
        </SectionCardHeader>
        <SectionCardContent>
          <Textarea
            className="min-h-[200px] font-mono text-xs leading-relaxed"
            value={data.system_prompt}
            onChange={(e) => update({ system_prompt: e.target.value })}
            placeholder="设定评估者的角色、原则与输出格式约束…"
          />
        </SectionCardContent>
      </SectionCard>

      {/* User Prompt Template（上下布局，始终可见） */}
      <SectionCard>
        <SectionCardHeader className="flex-row items-center justify-between pb-2">
          <SectionCardTitle className="text-sm">User Prompt Template（Jinja2）</SectionCardTitle>
          {vars.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {vars.map((v) => (
                <Badge key={v} variant="outline" className="font-mono text-[10px] text-blue-400">{`{{ ${v} }}`}</Badge>
              ))}
            </div>
          )}
        </SectionCardHeader>
        <SectionCardContent>
          <Textarea
            className="min-h-[200px] font-mono text-xs leading-relaxed"
            value={data.user_prompt_template}
            onChange={(e) => update({ user_prompt_template: e.target.value })}
            placeholder="用 {{ var }} 引用变量，描述评估对象、标准与输出要求…"
          />
        </SectionCardContent>
      </SectionCard>

      {/* 渲染预览 */}
      <SectionCard>
        <SectionCardHeader className="pb-2">
          <SectionCardTitle className="flex items-center gap-1.5 text-sm"><Eye className="size-3.5" /> 渲染预览</SectionCardTitle>
        </SectionCardHeader>
        <SectionCardContent className="space-y-3">
          {/* 变量 Mock 值 */}
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
          <div>
            <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">System</p>
            <pre className="max-h-[200px] overflow-auto whitespace-pre-wrap rounded-md bg-muted/20 p-3 font-mono text-xs leading-relaxed text-muted-foreground">{data.system_prompt || "(空)"}</pre>
          </div>
          <div>
            <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">User（渲染后）</p>
            <pre className="max-h-[200px] overflow-auto whitespace-pre-wrap rounded-md bg-muted/20 p-3 font-mono text-xs leading-relaxed text-muted-foreground">{rendered || "(空)"}</pre>
          </div>
        </SectionCardContent>
      </SectionCard>

      {/* 评分维度（output_schema） */}
      {data.dimensions && data.dimensions.length > 0 && (
        <SectionCard>
          <SectionCardHeader><SectionCardTitle className="text-sm">评分维度（output_schema）</SectionCardTitle></SectionCardHeader>
          <SectionCardContent>
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
          </SectionCardContent>
        </SectionCard>
      )}
    </div>
  )
}
