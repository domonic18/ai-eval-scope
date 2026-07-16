/**
 * 场景包创建向导 — 双模式（AI 对话占位 / 步骤向导）。
 *
 * 首屏选择模式 → 进入对应内容：
 * - AI 对话：占位，点击后提示「开发中」
 * - 步骤向导：8 步引导（信息→阶段→规则→提示词→数据→指标→策略→预览），调用已有 API
 */

import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useCrumbs } from "../../components/AppShell"
import { Page, PageHead } from "../../components/shared"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/shadcn/card"
import { Badge } from "../../components/shadcn/badge"
import { Button } from "../../components/shadcn/button"
import { Input } from "../../components/shadcn/input"
import { Label } from "../../components/shadcn/label"
import { Textarea } from "../../components/shadcn/textarea"
import { toast } from "sonner"
import { api } from "../../api/client"
import { ArrowLeft, ChevronRight, Plus, Sparkles, Trash2, ClipboardList } from "lucide-react"

type Mode = "select" | "ai" | "wizard"

// ── 步骤定义 ──
const STEPS = [
  { id: 1, title: "基本信息", required: "must" as const },
  { id: 2, title: "级联阶段", required: "must" as const },
  { id: 3, title: "规则配置", required: "must" as const },
  { id: 4, title: "提示词绑定", required: "cond" as const },
  { id: 5, title: "参考数据", required: "opt" as const },
  { id: 6, title: "指标定义", required: "must" as const },
  { id: 7, title: "聚合策略", required: "must" as const },
  { id: 8, title: "确认预览", required: "" as const },
]
const REQ_BADGE: Record<string, string> = { must: "必选", cond: "条件必选", opt: "可选", "": "" }
const REQ_COLOR: Record<string, string> = {
  must: "bg-red-500/15 text-red-400",
  cond: "bg-yellow-500/15 text-yellow-400",
  opt: "bg-muted text-muted-foreground",
  "": "",
}

export default function PackageWizard() {
  const { setCrumbs } = useCrumbs()
  const nav = useNavigate()
  const [mode, setMode] = useState<Mode>("select")

  useState(() => setCrumbs([{ label: "配置中心", to: "/config" }, { label: "创建场景包" }]))

  return (
    <Page>
      <PageHead title="创建场景包" sub="选择创建方式，配置评估规则、提示词、指标与聚合策略" />

      {mode === "select" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <button
            onClick={() => setMode("ai")}
            className="group flex items-center gap-4 rounded-lg border border-border bg-card p-5 text-left transition-all hover:border-primary/50 hover:shadow-md"
          >
            <Sparkles className="size-7 shrink-0 text-primary" />
            <div className="min-w-0 flex-1">
              <div className="text-base font-semibold">AI 对话创建</div>
              <p className="mt-0.5 text-sm text-muted-foreground">
                描述评估目标，AI 自动生成规则集 / 提示词 / 指标草案
              </p>
            </div>
            <Badge className="shrink-0">推荐</Badge>
          </button>
          <button
            onClick={() => setMode("wizard")}
            className="group flex items-center gap-4 rounded-lg border border-border bg-card p-5 text-left transition-all hover:border-primary/50 hover:shadow-md"
          >
            <ClipboardList className="size-7 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="text-base font-semibold">步骤向导</div>
              <p className="mt-0.5 text-sm text-muted-foreground">
                8 步逐项配置：清单 → 阶段 → 规则 → 提示词 → 指标
              </p>
            </div>
            <Badge variant="secondary" className="shrink-0">精细</Badge>
          </button>
        </div>
      )}

      {mode === "ai" && <AIPlaceholder onBack={() => setMode("select")} />}

      {mode === "wizard" && <StepWizard onBack={() => setMode("select")} onDone={(id) => nav(`/config/scenarios/${id}/edit`)} />}
    </Page>
  )
}

// ── AI 占位 ──
function AIPlaceholder({ onBack }: { onBack: () => void }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}><ArrowLeft className="mr-1 size-4" />返回选择</Button>
        <span className="text-sm font-medium">🤖 AI 对话创建</span>
      </div>
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <Sparkles className="size-10 text-primary/60" />
          <h3 className="text-lg font-semibold">AI 对话创建</h3>
          <p className="max-w-md text-sm text-muted-foreground">
            通过自然语言描述评估需求，AI 将自动生成规则集、提示词、指标定义和聚合策略草案。
            您可以在草案基础上二次编辑。
          </p>
          <Button
            onClick={() => toast.info("AI 对话创建功能开发中，敬请期待！\n当前请使用「步骤向导」模式创建场景包。")}
          >
            <Sparkles className="mr-1 size-4" /> 开始对话
          </Button>
          <p className="mt-2 text-xs text-muted-foreground/60">预计在后续版本上线</p>
        </CardContent>
      </Card>
    </div>
  )
}

// ── 步骤向导 ──
interface PkgData {
  scenarioId: string
  packageName: string
  name: string
  description: string
  stages: { stage: string; name: string; stop_on_fail: boolean }[]
  rules: { id: string; name: string; stage: string; evaluator: string; dimension: string; weight: number }[]
  metrics: { id: string; name: string; expression: string; threshold: number | null }[]
  policy: { stage_id: string; weight: number; is_gate: boolean }[]
}

const DEFAULT_DATA: PkgData = {
  scenarioId: "",
  packageName: "",
  name: "",
  description: "",
  stages: [
    { stage: "format", name: "格式门控", stop_on_fail: true },
    { stage: "quality", name: "质量评估", stop_on_fail: false },
  ],
  rules: [{ id: "FMT_001", name: "格式检查", stage: "format", evaluator: "format.response_format", dimension: "functional", weight: 1 }],
  metrics: [{ id: "document_rate", name: "交付率", expression: "count(format_gate) / total", threshold: 0.95 }],
  policy: [
    { stage_id: "format", weight: 1, is_gate: true },
    { stage_id: "quality", weight: 1, is_gate: false },
  ],
}

function StepWizard({ onBack, onDone }: { onBack: () => void; onDone: (scenarioId: string) => void }) {
  const [step, setStep] = useState(1)
  const [data, setData] = useState<PkgData>(DEFAULT_DATA)
  const [busy, setBusy] = useState(false)
  const update = (p: Partial<PkgData>) => setData({ ...data, ...p })

  const publish = async () => {
    if (!data.scenarioId || !data.name) {
      toast.error("请填写场景 ID 和名称")
      setStep(1)
      return
    }
    setBusy(true)
    try {
      // 1. 创建场景
      await api.createScenario(data.scenarioId, data.name, data.description)
      // 2. 发布规则集
      const ruleSetContent = {
        version: "1.0",
        scenario: data.scenarioId,
        description: data.description,
        dimensions: [{ id: "functional", name: "功能性", weight: 1 }],
        cascade: data.stages.map((s) => ({ stage: s.stage, name: s.name, stop_on_fail: s.stop_on_fail })),
        rules: data.rules.map((r) => ({
          id: r.id, name: r.name, stage: r.stage, dimension: r.dimension,
          evaluator: r.evaluator, weight: r.weight,
        })),
      }
      await api.publishAsset(data.scenarioId, "rule-sets", { asset_id: data.packageName || "quality", version: "1.0.0", labels: ["latest"], content: ruleSetContent })
      toast.success("场景包创建成功！")
      onDone(data.scenarioId)
    } catch (e) {
      toast.error((e as any)?.response?.data?.error ?? "创建失败")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* 顶部：返回 + 步骤进度 */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack}><ArrowLeft className="mr-1 size-4" />返回选择</Button>
        <span className="text-sm font-medium">📋 步骤向导</span>
      </div>

      {/* 步骤进度条 */}
      <div className="flex items-center gap-1 overflow-x-auto pb-2">
        {STEPS.map((s, i) => (
          <div key={s.id} className="flex items-center gap-1">
            <button
              onClick={() => s.id < step && setStep(s.id)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs transition-colors ${
                s.id === step ? "bg-accent font-medium text-accent-foreground"
                : s.id < step ? "text-muted-foreground hover:bg-accent/50" : "text-muted-foreground/50"
              }`}
            >
              <span className={`flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] ${
                s.id < step ? "bg-emerald-500/20 text-emerald-400"
                : s.id === step ? "bg-primary text-primary-foreground" : "bg-muted"
              }`}>{s.id < step ? "✓" : s.id}</span>
              <span className="hidden sm:inline">{s.title}</span>
              {s.required && <span className={`shrink-0 rounded px-1 text-[8px] font-medium ${REQ_COLOR[s.required]}`}>{REQ_BADGE[s.required]}</span>}
            </button>
            {i < STEPS.length - 1 && <ChevronRight className="size-3 shrink-0 text-muted-foreground/40" />}
          </div>
        ))}
      </div>

      {/* 步骤内容 */}
      <Card><CardContent className="p-6">

        {/* Step 1: 基本信息 */}
        {step === 1 && (
          <div className="space-y-4">
            <StepTitle step={1} title="基本信息" required="must" />
            <div className="grid grid-cols-2 gap-3">
              <div><Label>场景 ID *</Label><Input className="font-mono" placeholder="如 travel-itinerary" value={data.scenarioId} onChange={(e) => update({ scenarioId: e.target.value })} /></div>
              <div><Label>包 ID *</Label><Input className="font-mono" placeholder="如 quality" value={data.packageName} onChange={(e) => update({ packageName: e.target.value })} /></div>
              <div className="col-span-2"><Label>场景名称 *</Label><Input placeholder="如 研学行程规划评估" value={data.name} onChange={(e) => update({ name: e.target.value })} /></div>
              <div className="col-span-2"><Label>描述</Label><Textarea placeholder="简要描述评估目标..." value={data.description} onChange={(e) => update({ description: e.target.value })} /></div>
            </div>
          </div>
        )}

        {/* Step 2: 级联阶段 */}
        {step === 2 && (
          <div className="space-y-3">
            <StepTitle step={2} title="级联阶段" required="must" hint="阶段决定评估顺序。门控阶段失败会短路后续阶段。" />
            {data.stages.map((s, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-6 text-center text-xs text-muted-foreground">{i + 1}</span>
                <Input className="w-32 font-mono text-xs" value={s.stage} onChange={(e) => { const a = [...data.stages]; a[i] = { ...s, stage: e.target.value }; update({ stages: a }) }} />
                <Input className="flex-1" value={s.name} onChange={(e) => { const a = [...data.stages]; a[i] = { ...s, name: e.target.value }; update({ stages: a }) }} />
                <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={s.stop_on_fail} onChange={(e) => { const a = [...data.stages]; a[i] = { ...s, stop_on_fail: e.target.checked }; update({ stages: a }) }} />短路</label>
                <Button size="sm" variant="ghost" className="text-red-400" onClick={() => update({ stages: data.stages.filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></Button>
              </div>
            ))}
            <Button size="sm" variant="outline" onClick={() => update({ stages: [...data.stages, { stage: "", name: "", stop_on_fail: false }] })}><Plus className="mr-1 size-3" />添加阶段</Button>
          </div>
        )}

        {/* Step 3: 规则 */}
        {step === 3 && (
          <div className="space-y-3">
            <StepTitle step={3} title="规则配置" required="must" hint="每条规则绑定一个评估器，决定评估方式（规则检查 / LLM Judge）。" />
            {data.rules.map((r, i) => (
              <div key={i} className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2">
                  <Input className="w-28 font-mono text-xs" placeholder="ID" value={r.id} onChange={(e) => { const a = [...data.rules]; a[i] = { ...r, id: e.target.value }; update({ rules: a }) }} />
                  <Input className="flex-1" placeholder="规则名称" value={r.name} onChange={(e) => { const a = [...data.rules]; a[i] = { ...r, name: e.target.value }; update({ rules: a }) }} />
                  <Button size="sm" variant="ghost" className="text-red-400" onClick={() => update({ rules: data.rules.filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></Button>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <select className="rounded-md border bg-background px-2 py-1 text-xs" value={r.stage} onChange={(e) => { const a = [...data.rules]; a[i] = { ...r, stage: e.target.value }; update({ rules: a }) }}>
                    <option value="">阶段...</option>
                    {data.stages.map((s) => <option key={s.stage} value={s.stage}>{s.stage}</option>)}
                  </select>
                  <Input className="flex-1 font-mono text-xs" placeholder="evaluator (如 soft.teaching_logic)" value={r.evaluator} onChange={(e) => { const a = [...data.rules]; a[i] = { ...r, evaluator: e.target.value }; update({ rules: a }) }} />
                  <Input className="w-16" type="number" value={r.weight} onChange={(e) => { const a = [...data.rules]; a[i] = { ...r, weight: parseFloat(e.target.value) || 1 }; update({ rules: a }) }} />
                </div>
              </div>
            ))}
            <Button size="sm" variant="outline" onClick={() => update({ rules: [...data.rules, { id: "", name: "", stage: "", evaluator: "", dimension: "functional", weight: 1 }] })}><Plus className="mr-1 size-3" />添加规则</Button>
          </div>
        )}

        {/* Step 4: 提示词 (conditional) */}
        {step === 4 && (
          <div className="space-y-3">
            <StepTitle step={4} title="提示词绑定" required="cond" hint="仅 LLM-judge 评估器需要提示词。规则集创建后可在包编辑器中逐个配置。" />
            <Card><CardContent className="py-6 text-center text-sm text-muted-foreground">
              提示词将在场景包创建后于包编辑器中配置。<br />
              此步骤可跳过——系统会标记需要提示词的规则。
            </CardContent></Card>
          </div>
        )}

        {/* Step 5: 参考数据 (optional) */}
        {step === 5 && (
          <div className="space-y-3">
            <StepTitle step={5} title="参考数据" required="opt" hint="参考数据用于事实验证类评估器。无则跳过。" />
            <Card><CardContent className="py-6 text-center text-sm text-muted-foreground">
              参考数据可在场景包创建后于包编辑器中关联。
            </CardContent></Card>
          </div>
        )}

        {/* Step 6: 指标 */}
        {step === 6 && (
          <div className="space-y-3">
            <StepTitle step={6} title="指标定义" required="must" hint="指标表达式引用阶段分数，如 count(format_gate)/total" />
            {data.metrics.map((m, i) => (
              <div key={i} className="flex items-center gap-2">
                <Input className="w-40 font-mono text-xs" placeholder="指标 id" value={m.id} onChange={(e) => { const a = [...data.metrics]; a[i] = { ...m, id: e.target.value }; update({ metrics: a }) }} />
                <Input className="flex-1" placeholder="名称" value={m.name} onChange={(e) => { const a = [...data.metrics]; a[i] = { ...m, name: e.target.value }; update({ metrics: a }) }} />
                <Input className="w-48 font-mono text-xs" placeholder="expression" value={m.expression} onChange={(e) => { const a = [...data.metrics]; a[i] = { ...m, expression: e.target.value }; update({ metrics: a }) }} />
                <Input className="w-16" type="number" step="0.05" placeholder="阈值" value={m.threshold ?? ""} onChange={(e) => { const a = [...data.metrics]; a[i] = { ...m, threshold: e.target.value ? parseFloat(e.target.value) : null }; update({ metrics: a }) }} />
                <Button size="sm" variant="ghost" className="text-red-400" onClick={() => update({ metrics: data.metrics.filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></Button>
              </div>
            ))}
            <Button size="sm" variant="outline" onClick={() => update({ metrics: [...data.metrics, { id: "", name: "", expression: "", threshold: null }] })}><Plus className="mr-1 size-3" />添加指标</Button>
          </div>
        )}

        {/* Step 7: 聚合策略 */}
        {step === 7 && (
          <div className="space-y-3">
            <StepTitle step={7} title="聚合策略" required="must" hint="权重决定各阶段对 Reward 的贡献。" />
            {data.policy.map((p, i) => (
              <div key={i} className="flex items-center gap-2">
                <Input className="w-32 font-mono text-xs" value={p.stage_id} onChange={(e) => { const a = [...data.policy]; a[i] = { ...p, stage_id: e.target.value }; update({ policy: a }) }} />
                <Input className="w-16" type="number" step="0.1" value={p.weight} onChange={(e) => { const a = [...data.policy]; a[i] = { ...p, weight: parseFloat(e.target.value) || 1 }; update({ policy: a }) }} />
                <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={p.is_gate} onChange={(e) => { const a = [...data.policy]; a[i] = { ...p, is_gate: e.target.checked }; update({ policy: a }) }} />门控</label>
              </div>
            ))}
            <Button size="sm" variant="outline" onClick={() => update({ policy: [...data.policy, { stage_id: "", weight: 1, is_gate: false }] })}><Plus className="mr-1 size-3" />添加阶段权重</Button>
          </div>
        )}

        {/* Step 8: 预览 + 发布 */}
        {step === 8 && (
          <div className="space-y-4">
            <StepTitle step={8} title="确认预览" />
            <pre className="max-h-[400px] overflow-auto rounded-md bg-muted/20 p-4 font-mono text-xs text-muted-foreground">
{JSON.stringify({
  scenario: data.scenarioId,
  name: data.name,
  stages: data.stages.length,
  rules: data.rules.length,
  metrics: data.metrics.length,
  policy: data.policy.length,
}, null, 2)}
            </pre>
            <Button onClick={publish} disabled={busy} className="w-full"><Sparkles className="mr-1 size-4" />{busy ? "创建中…" : "创建场景包"}</Button>
          </div>
        )}
      </CardContent></Card>

      {/* 底部导航 */}
      <div className="flex justify-between">
        <Button variant="outline" disabled={step === 1} onClick={() => setStep(step - 1)}>上一步</Button>
        {step < 8 ? (
          <Button onClick={() => setStep(step + 1)}>下一步</Button>
        ) : (
          <Button onClick={publish} disabled={busy}>{busy ? "创建中…" : "创建"}</Button>
        )}
      </div>
    </div>
  )
}

function StepTitle({ step, title, required = "", hint }: { step: number; title: string; required?: string; hint?: string }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <h3 className="text-base font-semibold">步骤 {step}：{title}</h3>
        {required && <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${REQ_COLOR[required]}`}>{REQ_BADGE[required]}</span>}
      </div>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}
