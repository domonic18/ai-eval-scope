/**
 * 场景默认聚合策略编辑器（表单 + YAML 切换）。
 * 直接 PATCH Scenario.defaultAggregationPolicy（场景级默认值，非版本化资产）。
 */
import { useEffect, useState } from "react"
import * as yaml from "js-yaml"
import { CardContent } from "../../../components/shadcn/card"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Textarea } from "../../../components/shadcn/textarea"
import { Plus, Save, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { api } from "../../../api/client"
import { AddButton, SectionCard, SectionCardHeader, SectionCardTitle } from "../../../components/shared"
import { Field, FormYamlToggle } from "./Field"

interface StageWeight {
  stage_id: string
  id?: string
  weight?: number
  is_gate?: boolean
}
interface AggPolicy {
  id?: string
  stage_weights?: StageWeight[]
  [k: string]: unknown
}

const errMsg = (e: unknown) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? "保存失败"

const normalize = (raw: Record<string, unknown> | null): AggPolicy => {
  if (!raw || typeof raw !== "object") return { stage_weights: [] }
  const p = raw as AggPolicy
  if (!Array.isArray(p.stage_weights)) p.stage_weights = []
  return p
}

export function AggregationPolicyEditor({ scenarioId }: { scenarioId: string }) {
  const [policy, setPolicy] = useState<AggPolicy>({ stage_weights: [] })
  const [yamlText, setYamlText] = useState("")
  const [mode, setMode] = useState<"form" | "yaml">("form")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .scenarioAggregationPolicy(scenarioId)
      .then((p) => {
        const np = normalize(p)
        setPolicy(np)
        setYamlText(yaml.dump(np, { sortKeys: false }))
      })
      .catch(() => {
        setPolicy({ stage_weights: [] })
        setYamlText("stage_weights: []")
      })
      .finally(() => setLoading(false))
  }, [scenarioId])

  const syncYaml = (p: AggPolicy) => setYamlText(yaml.dump(p, { sortKeys: false }))
  const setWeights = (w: StageWeight[]) => {
    const np = { ...policy, stage_weights: w }
    setPolicy(np)
    syncYaml(np)
  }
  const updateW = (i: number, patch: Partial<StageWeight>) => {
    const w = [...(policy.stage_weights ?? [])]
    w[i] = { ...w[i], ...patch }
    setWeights(w)
  }
  const addW = () => setWeights([...(policy.stage_weights ?? []), { stage_id: "", weight: 1, is_gate: false }])
  const removeW = (i: number) => setWeights((policy.stage_weights ?? []).filter((_, j) => j !== i))
  const onYamlChange = (text: string) => {
    setYamlText(text)
    try {
      const parsed = yaml.load(text)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        setPolicy(normalize(parsed as Record<string, unknown>))
      }
    } catch {
      /* YAML 语法错误时保留编辑 */
    }
  }
  const switchMode = (m: "form" | "yaml") => {
    if (m === "yaml") setYamlText(yaml.dump(policy, { sortKeys: false }))
    setMode(m)
  }
  const save = async () => {
    setBusy(true)
    try {
      await api.updateScenarioDefaults(scenarioId, { aggregationPolicy: policy })
      toast.success("聚合策略已保存")
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <SectionCard>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">加载中…</CardContent>
      </SectionCard>
    )
  }

  return (
    <SectionCard>
      <SectionCardHeader className="flex-row items-center justify-between">
        <SectionCardTitle>聚合策略（场景默认）</SectionCardTitle>
        <FormYamlToggle mode={mode} onChange={switchMode} />
      </SectionCardHeader>
      <CardContent className="space-y-3">
        {mode === "form" ? (
          <>
            <Field label="策略 id" optional hint="聚合策略标识，可空">
              <Input className="font-mono text-xs" value={policy.id ?? ""} onChange={(e) => { const np = { ...policy, id: e.target.value }; setPolicy(np); syncYaml(np) }} />
            </Field>
            <div className="space-y-2">
              <p className="text-[11px] text-muted-foreground">阶段权重（stage_weights）：决定各阶段在总分中的权重，门控阶段失败可短路。</p>
              {(policy.stage_weights ?? []).map((w, i) => (
                <div key={i} className="flex items-end gap-2">
                  <div className="min-w-0 flex-1">
                    <Field label="stage_id" required hint="阶段标识，需与规则集级联阶段对应">
                      <Input className="font-mono text-xs" value={w.stage_id} onChange={(e) => updateW(i, { stage_id: e.target.value })} />
                    </Field>
                  </div>
                  <div className="w-24">
                    <Field label="weight" optional hint="权重">
                      <Input type="number" className="font-mono text-xs" value={w.weight ?? 0} onChange={(e) => updateW(i, { weight: Number(e.target.value) })} />
                    </Field>
                  </div>
                  <label className="flex items-center gap-1 pb-2 text-[11px] text-muted-foreground">
                    <input type="checkbox" checked={w.is_gate ?? false} onChange={(e) => updateW(i, { is_gate: e.target.checked })} />
                    门控
                  </label>
                  <Button size="sm" variant="ghost" className="text-red-400" onClick={() => removeW(i)}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              ))}
              <AddButton onClick={addW}>添加阶段权重</AddButton>
            </div>
          </>
        ) : (
          <>
            <p className="text-[11px] text-muted-foreground">YAML 模式可编辑完整聚合策略；保存以当前解析结构为准。</p>
            <Textarea className="min-h-[300px] font-mono text-xs leading-relaxed" value={yamlText} onChange={(e) => onYamlChange(e.target.value)} />
          </>
        )}
        <Button onClick={save} disabled={busy}>
          <Save className="mr-1 size-4" />{busy ? "保存中…" : "保存"}
        </Button>
      </CardContent>
    </SectionCard>
  )
}
