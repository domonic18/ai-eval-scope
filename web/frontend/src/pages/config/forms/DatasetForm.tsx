/**
 * 数据集结构化编辑表单（P4-4）。
 * role 切换（reference/test）；reference: 常量/误区可编辑表格；test: reader/infer/eval 配置。
 * 基本信息与子配置均带填写提示 + 必填/选填标识。
 */
import { CardContent } from "../../../components/shadcn/card"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Trash2 } from "lucide-react"
import { AddButton, SectionCard, SectionCardHeader, SectionCardTitle } from "../../../components/shared"
import { Field } from "./Field"

export interface DatasetData {
  subject?: string
  description?: string
  version?: string
  role: "reference" | "test"
  backend_type?: string
  constants?: { name: string; extract_pattern?: string; value: number | string; tolerance?: number; description?: string }[]
  misconceptions?: { pattern: string; correct?: string; severity?: string; description?: string }[]
  reader_cfg?: { input_columns?: string[]; output_column?: string }
  infer_cfg?: { prompt_template_id?: string; inferencer?: string; max_out_len?: number }
  eval_cfg?: { evaluator?: string; pred_postprocessor?: string }
}

export function DatasetForm({
  data,
  onChange,
}: {
  data: DatasetData
  onChange: (d: DatasetData) => void
}) {
  const update = (patch: Partial<DatasetData>) => onChange({ ...data, ...patch })

  return (
    <div className="space-y-4">
      {/* 基本信息 */}
      <SectionCard>
        <CardContent className="grid grid-cols-3 gap-3 p-4">
          <Field label="subject" required hint="主题/学科标识，如 math / safety">
            <Input value={data.subject ?? ""} onChange={(e) => update({ subject: e.target.value })} />
          </Field>
          <Field label="version" optional hint="数据集版本号，如 1.0">
            <Input value={data.version ?? ""} onChange={(e) => update({ version: e.target.value })} />
          </Field>
          <Field label="role" required hint="reference=参考知识（供规则校验）；test=测试样本">
            <div className="flex gap-2 pt-1">
              <button onClick={() => update({ role: "reference" })} className={`rounded-md px-3 py-1.5 text-sm ${data.role === "reference" ? "bg-primary font-medium text-primary-foreground" : "border text-muted-foreground"}`}>reference</button>
              <button onClick={() => update({ role: "test" })} className={`rounded-md px-3 py-1.5 text-sm ${data.role === "test" ? "bg-primary font-medium text-primary-foreground" : "border text-muted-foreground"}`}>test</button>
            </div>
          </Field>
          <div className="col-span-3">
            <Field label="描述" optional hint="数据集用途/内容说明，便于他人理解">
              <Input value={data.description ?? ""} onChange={(e) => update({ description: e.target.value })} />
            </Field>
          </div>
        </CardContent>
      </SectionCard>

      {data.role === "reference" ? (
        <>
          {/* 常量/公式 */}
          <SectionCard>
            <SectionCardHeader><SectionCardTitle className="text-sm">常量/公式（{data.constants?.length ?? 0}）</SectionCardTitle></SectionCardHeader>
            <CardContent className="space-y-2">
              <p className="text-[10px] text-muted-foreground">用于事实校验的已知常量/公式：名称、抽取正则、标准值与容差。</p>
              {(data.constants ?? []).map((c, i) => (
                <div key={i} className="flex items-start gap-2">
                  <Input className="min-w-0 flex-1 text-xs" placeholder="名称（如 圆周率）" value={c.name} onChange={(e) => { const arr = [...(data.constants ?? [])]; arr[i] = { ...c, name: e.target.value }; update({ constants: arr }) }} />
                  <Input className="w-40 shrink-0 font-mono text-xs" placeholder="extract_pattern（正则）" value={c.extract_pattern ?? ""} onChange={(e) => { const arr = [...(data.constants ?? [])]; arr[i] = { ...c, extract_pattern: e.target.value }; update({ constants: arr }) }} />
                  <Input className="w-20 shrink-0 font-mono text-xs" placeholder="value" value={c.value} onChange={(e) => { const arr = [...(data.constants ?? [])]; arr[i] = { ...c, value: e.target.value }; update({ constants: arr }) }} />
                  <Input className="w-16 shrink-0 text-xs" placeholder="±tol" value={c.tolerance ?? ""} onChange={(e) => { const arr = [...(data.constants ?? [])]; arr[i] = { ...c, tolerance: parseFloat(e.target.value) || 0 }; update({ constants: arr }) }} />
                  <Button size="sm" variant="ghost" className="text-red-400" onClick={() => update({ constants: (data.constants ?? []).filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></Button>
                </div>
              ))}
              <AddButton onClick={() => update({ constants: [...(data.constants ?? []), { name: "", value: 0 }] })}>
                添加
              </AddButton>
            </CardContent>
          </SectionCard>

          {/* 常见误区 */}
          <SectionCard>
            <SectionCardHeader><SectionCardTitle className="text-sm">常见误区（{data.misconceptions?.length ?? 0}）</SectionCardTitle></SectionCardHeader>
            <CardContent className="space-y-2">
              <p className="text-[10px] text-muted-foreground">匹配常见错误模式并给出正确答案；error 级会直接判错，warning 级仅扣分。</p>
              {(data.misconceptions ?? []).map((m, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span className={`mt-1 shrink-0 font-mono text-[10px] font-semibold ${m.severity === "error" ? "text-destructive" : "text-warning"}`}>{m.severity ?? "warning"}</span>
                  <Input className="min-w-0 flex-1 font-mono text-xs" placeholder="pattern（错误模式正则）" value={m.pattern} onChange={(e) => { const arr = [...(data.misconceptions ?? [])]; arr[i] = { ...m, pattern: e.target.value }; update({ misconceptions: arr }) }} />
                  <Input className="w-32 shrink-0 text-xs text-emerald-400" placeholder="→ correct（正确答案）" value={m.correct ?? ""} onChange={(e) => { const arr = [...(data.misconceptions ?? [])]; arr[i] = { ...m, correct: e.target.value }; update({ misconceptions: arr }) }} />
                  <select className="shrink-0 rounded-md border border-border bg-secondary px-1 py-1 text-xs text-foreground" value={m.severity ?? "warning"} onChange={(e) => { const arr = [...(data.misconceptions ?? [])]; arr[i] = { ...m, severity: e.target.value }; update({ misconceptions: arr }) }}>
                    <option value="warning">warning</option>
                    <option value="error">error</option>
                  </select>
                  <Button size="sm" variant="ghost" className="text-red-400" onClick={() => update({ misconceptions: (data.misconceptions ?? []).filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></Button>
                </div>
              ))}
              <AddButton onClick={() => update({ misconceptions: [...(data.misconceptions ?? []), { pattern: "", severity: "warning" }] })}>
                添加
              </AddButton>
            </CardContent>
          </SectionCard>
        </>
      ) : (
        /* test 模式 */
        <div className="grid gap-4 sm:grid-cols-3">
          <SectionCard>
            <SectionCardHeader><SectionCardTitle className="text-sm">读取配置 reader_cfg</SectionCardTitle></SectionCardHeader>
            <CardContent className="space-y-2">
              <Field label="output_column" optional hint="样本中作为模型输出的列名">
                <Input className="text-xs" value={data.reader_cfg?.output_column ?? ""} onChange={(e) => update({ reader_cfg: { ...data.reader_cfg, output_column: e.target.value } })} />
              </Field>
            </CardContent>
          </SectionCard>
          <SectionCard>
            <SectionCardHeader><SectionCardTitle className="text-sm">推理配置 infer_cfg</SectionCardTitle></SectionCardHeader>
            <CardContent className="space-y-2">
              <Field label="prompt_template_id" optional hint="推理时使用的提示词 id">
                <Input className="font-mono text-xs" value={data.infer_cfg?.prompt_template_id ?? ""} onChange={(e) => update({ infer_cfg: { ...data.infer_cfg, prompt_template_id: e.target.value } })} />
              </Field>
              <Field label="inferencer" optional hint="推理后端类型（如 gen / ppl）">
                <Input className="text-xs" value={data.infer_cfg?.inferencer ?? ""} onChange={(e) => update({ infer_cfg: { ...data.infer_cfg, inferencer: e.target.value } })} />
              </Field>
              <Field label="max_out_len" optional hint="最大输出 token 数">
                <Input type="number" className="text-xs" value={data.infer_cfg?.max_out_len ?? 512} onChange={(e) => update({ infer_cfg: { ...data.infer_cfg, max_out_len: parseInt(e.target.value) || 512 } })} />
              </Field>
            </CardContent>
          </SectionCard>
          <SectionCard>
            <SectionCardHeader><SectionCardTitle className="text-sm">评估配置 eval_cfg</SectionCardTitle></SectionCardHeader>
            <CardContent className="space-y-2">
              <Field label="evaluator" optional hint="评估器 id（如 format.json_validity）">
                <Input className="font-mono text-xs" value={data.eval_cfg?.evaluator ?? ""} onChange={(e) => update({ eval_cfg: { ...data.eval_cfg, evaluator: e.target.value } })} />
              </Field>
              <Field label="pred_postprocessor" optional hint="预测结果后处理器 id">
                <Input className="text-xs" value={data.eval_cfg?.pred_postprocessor ?? ""} onChange={(e) => update({ eval_cfg: { ...data.eval_cfg, pred_postprocessor: e.target.value } })} />
              </Field>
            </CardContent>
          </SectionCard>
        </div>
      )}
    </div>
  )
}
