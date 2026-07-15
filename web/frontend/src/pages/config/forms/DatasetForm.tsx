/**
 * 数据集结构化编辑表单（P4-4）。
 * role 切换（reference/test）；reference: 常量/误区可编辑表格；test: reader/infer/eval 配置。
 */
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/shadcn/card"
import { Badge } from "../../../components/shadcn/badge"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Label } from "../../../components/shadcn/label"
import { Plus, Trash2 } from "lucide-react"

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
      {/* 元数据 */}
      <Card>
        <CardContent className="grid grid-cols-3 gap-3 p-4">
          <div><Label>subject</Label><Input value={data.subject ?? ""} onChange={(e) => update({ subject: e.target.value })} /></div>
          <div><Label>version</Label><Input value={data.version ?? ""} onChange={(e) => update({ version: e.target.value })} /></div>
          <div>
            <Label>role</Label>
            <div className="flex gap-2">
              <button onClick={() => update({ role: "reference" })} className={`rounded-md px-3 py-1.5 text-sm ${data.role === "reference" ? "bg-accent font-medium" : "border text-muted-foreground"}`}>reference</button>
              <button onClick={() => update({ role: "test" })} className={`rounded-md px-3 py-1.5 text-sm ${data.role === "test" ? "bg-accent font-medium" : "border text-muted-foreground"}`}>test</button>
            </div>
          </div>
          <div className="col-span-3"><Label>描述</Label><Input value={data.description ?? ""} onChange={(e) => update({ description: e.target.value })} /></div>
        </CardContent>
      </Card>

      {data.role === "reference" ? (
        <>
          {/* 常量/公式 */}
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="text-sm">常量/公式（{data.constants?.length ?? 0}）</CardTitle>
              <Button size="sm" variant="outline" onClick={() => update({ constants: [...(data.constants ?? []), { name: "", value: 0 }] })}><Plus className="mr-1 size-3" />添加</Button>
            </CardHeader>
            <CardContent className="space-y-2">
              {(data.constants ?? []).map((c, i) => (
                <div key={i} className="flex items-start gap-2">
                  <Input className="min-w-0 flex-1 text-xs" placeholder="名称" value={c.name} onChange={(e) => { const arr = [...(data.constants ?? [])]; arr[i] = { ...c, name: e.target.value }; update({ constants: arr }) }} />
                  <Input className="w-40 shrink-0 font-mono text-xs" placeholder="extract_pattern" value={c.extract_pattern ?? ""} onChange={(e) => { const arr = [...(data.constants ?? [])]; arr[i] = { ...c, extract_pattern: e.target.value }; update({ constants: arr }) }} />
                  <Input className="w-20 shrink-0 font-mono text-xs" placeholder="value" value={c.value} onChange={(e) => { const arr = [...(data.constants ?? [])]; arr[i] = { ...c, value: e.target.value }; update({ constants: arr }) }} />
                  <Input className="w-16 shrink-0 text-xs" placeholder="±tol" value={c.tolerance ?? ""} onChange={(e) => { const arr = [...(data.constants ?? [])]; arr[i] = { ...c, tolerance: parseFloat(e.target.value) || 0 }; update({ constants: arr }) }} />
                  <Button size="sm" variant="ghost" className="text-red-400" onClick={() => update({ constants: (data.constants ?? []).filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></Button>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* 常见误区 */}
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="text-sm">常见误区（{data.misconceptions?.length ?? 0}）</CardTitle>
              <Button size="sm" variant="outline" onClick={() => update({ misconceptions: [...(data.misconceptions ?? []), { pattern: "", severity: "warning" }] })}><Plus className="mr-1 size-3" />添加</Button>
            </CardHeader>
            <CardContent className="space-y-2">
              {(data.misconceptions ?? []).map((m, i) => (
                <div key={i} className="flex items-start gap-2">
                  <Badge variant={m.severity === "error" ? "destructive" : "secondary"} className="mt-1 shrink-0 text-[10px]">{m.severity ?? "warning"}</Badge>
                  <Input className="min-w-0 flex-1 font-mono text-xs" placeholder="pattern" value={m.pattern} onChange={(e) => { const arr = [...(data.misconceptions ?? [])]; arr[i] = { ...m, pattern: e.target.value }; update({ misconceptions: arr }) }} />
                  <Input className="w-32 shrink-0 text-xs text-emerald-400" placeholder="→ correct" value={m.correct ?? ""} onChange={(e) => { const arr = [...(data.misconceptions ?? [])]; arr[i] = { ...m, correct: e.target.value }; update({ misconceptions: arr }) }} />
                  <select className="shrink-0 rounded-md border bg-background px-1 py-1 text-xs" value={m.severity ?? "warning"} onChange={(e) => { const arr = [...(data.misconceptions ?? [])]; arr[i] = { ...m, severity: e.target.value }; update({ misconceptions: arr }) }}>
                    <option value="warning">warning</option>
                    <option value="error">error</option>
                  </select>
                  <Button size="sm" variant="ghost" className="text-red-400" onClick={() => update({ misconceptions: (data.misconceptions ?? []).filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></Button>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      ) : (
        /* test 模式 */
        <div className="grid gap-4 sm:grid-cols-3">
          <Card>
            <CardHeader><CardTitle className="text-sm">读取配置 reader_cfg</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <div><Label>output_column</Label><Input className="text-xs" value={data.reader_cfg?.output_column ?? ""} onChange={(e) => update({ reader_cfg: { ...data.reader_cfg, output_column: e.target.value } })} /></div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-sm">推理配置 infer_cfg</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <div><Label>prompt_template_id</Label><Input className="font-mono text-xs" value={data.infer_cfg?.prompt_template_id ?? ""} onChange={(e) => update({ infer_cfg: { ...data.infer_cfg, prompt_template_id: e.target.value } })} /></div>
              <div><Label>inferencer</Label><Input className="text-xs" value={data.infer_cfg?.inferencer ?? ""} onChange={(e) => update({ infer_cfg: { ...data.infer_cfg, inferencer: e.target.value } })} /></div>
              <div><Label>max_out_len</Label><Input type="number" className="text-xs" value={data.infer_cfg?.max_out_len ?? 512} onChange={(e) => update({ infer_cfg: { ...data.infer_cfg, max_out_len: parseInt(e.target.value) || 512 } })} /></div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-sm">评估配置 eval_cfg</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <div><Label>evaluator</Label><Input className="font-mono text-xs" value={data.eval_cfg?.evaluator ?? ""} onChange={(e) => update({ eval_cfg: { ...data.eval_cfg, evaluator: e.target.value } })} /></div>
              <div><Label>pred_postprocessor</Label><Input className="text-xs" value={data.eval_cfg?.pred_postprocessor ?? ""} onChange={(e) => update({ eval_cfg: { ...data.eval_cfg, pred_postprocessor: e.target.value } })} /></div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
