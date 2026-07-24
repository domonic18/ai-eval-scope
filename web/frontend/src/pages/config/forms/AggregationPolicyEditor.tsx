/**
 * 场景默认聚合策略编辑器（受控：data + onChange；可视化表单 + YAML）。
 * 数据来自 useEditorStore 的 defaults doc；发布走右侧 VersionTimeline（版本化），无独立 save。
 * metric_defs / cascade 仍拉取（AI 生成上下文 + 可视化辅助），不参与受控（只读）。
 */
import { useEffect, useState } from "react"
import * as yaml from "js-yaml"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Textarea } from "../../../components/shadcn/textarea"
import { Sparkles, Trash2, AlertTriangle, Plus, ArrowRight } from "lucide-react"
import { toast } from "sonner"
import { extractErr } from "../../../hooks/useAiGeneration"
import { api } from "../../../api/client"
import { AddButton, SectionCard, SectionCardContent, SectionCardHeader, SectionCardTitle } from "../../../components/shared"
import { AiResultDialog } from "../../../components/AiResultDialog"
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

const normalize = (raw: Record<string, unknown> | null | undefined): AggPolicy => {
  if (!raw || typeof raw !== "object") return { stage_weights: [] }
  const p = raw as AggPolicy
  if (!Array.isArray(p.stage_weights)) p.stage_weights = []
  return p
}
const STAGE_COLORS = ["#3d6ff", "#2fe6c8", "#d29922", "#f85149", "#a78bfa", "#3fb950"]

export function AggregationPolicyEditor({
  scenarioId,
  data,
  onChange,
}: {
  scenarioId: string
  data: Record<string, unknown> | null | undefined
  onChange: (p: Record<string, unknown>) => void
}) {
  const policy = normalize(data)
  const [mode, setMode] = useState<"form" | "yaml">("form")
  const [yamlText, setYamlText] = useState("")
  const [aiOpen, setAiOpen] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiPolicy, setAiPolicy] = useState<AggPolicy | null>(null)
  const [metricDefs, setMetricDefs] = useState<Array<{ id?: string; name?: string; threshold?: number | null; unit?: string | null }>>([])
  const [cascadeStages, setCascadeStages] = useState<Array<{ stage: string; name?: string; stop_on_fail?: boolean }>>([])

  useEffect(() => {
    api.scenarioDefaults(scenarioId).then((m) => setMetricDefs(m as Array<{ id?: string; name?: string; threshold?: number | null; unit?: string | null }>)).catch(() => {})
    api
      .scenarioCatalog(scenarioId)
      .then(async (c) => {
        const rs = c.rule_sets[0]
        if (!rs) return
        try {
          const content = await api.assetContent(scenarioId, "rule-sets", rs.asset_id)
          const cs = (content as { cascade?: Array<{ stage: string; name?: string; stop_on_fail?: boolean }> }).cascade
          if (Array.isArray(cs)) setCascadeStages(cs.map((x) => ({ stage: x.stage, name: x.name, stop_on_fail: x.stop_on_fail })))
        } catch {
          /* ignore */
        }
      })
      .catch(() => {})
  }, [scenarioId])

  const setWeights = (w: StageWeight[]) => onChange({ ...policy, stage_weights: w })
  const updateW = (i: number, patch: Partial<StageWeight>) => {
    const w = [...(policy.stage_weights ?? [])]
    w[i] = { ...w[i], ...patch }
    setWeights(w)
  }
  const removeW = (i: number) => setWeights((policy.stage_weights ?? []).filter((_, j) => j !== i))
  const onYamlChange = (text: string) => {
    setYamlText(text)
    try {
      const parsed = yaml.load(text)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) onChange(normalize(parsed as Record<string, unknown>))
    } catch {
      /* YAML 语法错误时保留编辑 */
    }
  }
  const switchMode = (m: "form" | "yaml") => {
    if (m === "yaml") setYamlText(yaml.dump(policy, { sortKeys: false }))
    setMode(m)
  }

  async function runAiGenerate() {
    setAiOpen(true)
    setAiLoading(true)
    setAiPolicy(null)
    try {
      const r = await api.aiGeneratePolicy({ scenario: scenarioId, cascade: cascadeStages, metricDefinitions: metricDefs })
      setAiPolicy(normalize(r.aggregationPolicy as Record<string, unknown> | null))
    } catch (e) {
      toast.error(extractErr(e, "AI 生成失败"))
    } finally {
      setAiLoading(false)
    }
  }
  function acceptAiPolicy() {
    if (!aiPolicy) return
    onChange(aiPolicy)
    setAiOpen(false)
    toast.success("已采纳 AI 生成的聚合策略")
  }

  const weights = policy.stage_weights ?? []
  const totalWeight = weights.reduce((s, w) => s + (w.weight ?? 0), 0) || 1
  const stageToWeightIdx = new Map<string, number>()
  weights.forEach((w, i) => stageToWeightIdx.set(w.stage_id, i))
  const orphanWeights = weights.map((w, i) => ({ w, i })).filter((x) => !cascadeStages.some((cs) => cs.stage === x.w.stage_id))
  function addStageWeight(stageId: string, isGate?: boolean) {
    setWeights([...weights, { stage_id: stageId, weight: 0.5, is_gate: isGate ?? false }])
  }

  return (
    <>
    <SectionCard>
      <SectionCardHeader className="flex-row items-center justify-between">
        <SectionCardTitle>聚合策略（场景默认）</SectionCardTitle>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={runAiGenerate}>
            <Sparkles className="mr-1 size-3.5" /> AI 生成
          </Button>
          <FormYamlToggle mode={mode} onChange={switchMode} />
        </div>
      </SectionCardHeader>
      <SectionCardContent className="space-y-4">
        {mode === "form" ? (
          <>
            <div className="rounded-lg border border-border bg-secondary/50 p-4">
              <p className="mb-3 text-xs font-semibold text-foreground">聚合策略如何工作</p>
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <span className="rounded-md border border-border bg-card px-2 py-1">级联阶段评估</span>
                <ArrowRight className="size-3 text-muted-foreground" />
                <span className="rounded-md border border-primary/40 bg-primary/10 px-2 py-1 font-medium text-primary">聚合策略加权</span>
                <ArrowRight className="size-3 text-muted-foreground" />
                <span className="rounded-md border border-border bg-card px-2 py-1">样本 Reward</span>
                <ArrowRight className="size-3 text-muted-foreground" />
                <span className="rounded-md border border-border bg-card px-2 py-1">指标定义计算</span>
                <ArrowRight className="size-3 text-muted-foreground" />
                <span className="rounded-md border border-border bg-card px-2 py-1">运行级指标</span>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                聚合策略为每个<b>级联阶段</b>分配权重和门控语义，加权合成样本级 Reward；指标定义再从 Reward 等字段计算运行级统计量。
              </p>
            </div>
            {weights.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-semibold text-muted-foreground">权重分布（各阶段在 Reward 中的占比）</p>
                <div className="flex h-7 overflow-hidden rounded-md border border-border">
                  {weights.map((w, i) => {
                    const pct = ((w.weight ?? 0) / totalWeight) * 100
                    const color = STAGE_COLORS[i % STAGE_COLORS.length]
                    const stage = cascadeStages.find((cs) => cs.stage === w.stage_id)
                    return (
                      <div
                        key={i}
                        style={{ width: `${Math.max(pct, 2)}%`, background: color }}
                        className="flex items-center justify-center overflow-hidden whitespace-nowrap text-[10px] font-semibold text-white transition-all"
                        title={`${stage?.name ?? w.stage_id}: ${w.weight} (${pct.toFixed(0)}%)`}
                      >
                        {pct > 8 ? `${stage?.name ?? w.stage_id} ${pct.toFixed(0)}%` : ""}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            {cascadeStages.length > 0 ? (
              <div className="space-y-2">
                <p className="text-[11px] font-semibold text-muted-foreground">级联阶段（来自规则集）→ 聚合权重配置</p>
                {cascadeStages.map((cs, si) => {
                  const wi = stageToWeightIdx.get(cs.stage)
                  const w = wi != null ? weights[wi] : null
                  const color = STAGE_COLORS[si % STAGE_COLORS.length]
                  const pct = w ? ((w.weight ?? 0) / totalWeight) * 100 : 0
                  return (
                    <div
                      key={cs.stage}
                      className={`rounded-md border p-3 transition-colors ${w ? "border-border bg-secondary" : "border-dashed border-muted-foreground/30 bg-transparent"}`}
                    >
                      <div className="flex items-center gap-3">
                        <div className="h-10 w-1 shrink-0 rounded-full" style={{ background: color }} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{cs.name || cs.stage}</span>
                            <span className="font-mono text-[10px] text-muted-foreground">{cs.stage}</span>
                            {cs.stop_on_fail && (
                              <span className="rounded-sm bg-destructive/15 px-1 py-px text-[9px] font-semibold text-destructive">门控阶段</span>
                            )}
                          </div>
                          {w ? (
                            <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                              <span>权重占比 {pct.toFixed(0)}%</span>
                              <span>·</span>
                              <span className={w.is_gate ? "text-destructive" : ""}>
                                {w.is_gate ? "门控语义（全过=1/任一失败=0）" : "加权平均"}
                              </span>
                            </div>
                          ) : (
                            <p className="mt-0.5 text-[10px] text-muted-foreground">尚未配置权重</p>
                          )}
                        </div>
                        {w ? (
                          <>
                            <div className="flex items-center gap-2">
                              <input
                                type="range"
                                min={0}
                                max={1}
                                step={0.05}
                                value={w.weight ?? 0}
                                onChange={(e) => updateW(wi!, { weight: parseFloat(e.target.value) })}
                                className="w-24 accent-primary"
                                title="拖动调整权重"
                              />
                              <Input
                                type="number"
                                step={0.05}
                                className="h-7 w-16 font-mono text-xs"
                                value={w.weight ?? 0}
                                onChange={(e) => updateW(wi!, { weight: parseFloat(e.target.value) || 0 })}
                              />
                            </div>
                            <label className="flex cursor-pointer items-center gap-1 text-[11px] text-muted-foreground" title="门控阶段：全过=1分，任一失败/跳过=0分">
                              <input
                                type="checkbox"
                                checked={w.is_gate ?? false}
                                onChange={(e) => updateW(wi!, { is_gate: e.target.checked })}
                                className="accent-destructive"
                              />
                              门控
                            </label>
                            <Button size="icon-xs" variant="ghost" className="text-red-400" onClick={() => removeW(wi!)}>
                              <Trash2 className="size-3.5" />
                            </Button>
                          </>
                        ) : (
                          <Button size="sm" variant="outline" onClick={() => addStageWeight(cs.stage, cs.stop_on_fail)}>
                            <Plus className="mr-1 size-3" />配置权重
                          </Button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-muted-foreground/30 p-4 text-center">
                <p className="text-xs text-muted-foreground">未检测到级联阶段（需先在规则集中配置 cascade）</p>
                <p className="mt-1 text-[11px] text-muted-foreground">可手动添加 stage_weights，或点「AI 生成」自动推断</p>
              </div>
            )}
            {orphanWeights.length > 0 && (
              <div className="rounded-md border border-warning/40 bg-warning/10 p-3">
                <p className="flex items-center gap-1.5 text-[11px] font-semibold text-warning">
                  <AlertTriangle className="size-3.5" />
                  以下权重的 stage_id 不在级联阶段中，可能是过期数据：
                </p>
                <div className="mt-2 space-y-1">
                  {orphanWeights.map(({ w, i }) => (
                    <div key={i} className="flex items-center gap-2 text-[11px]">
                      <span className="font-mono text-muted-foreground">{w.stage_id}</span>
                      <span>权重 {w.weight}</span>
                      <button className="text-destructive hover:underline" onClick={() => removeW(i)}>删除</button>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {cascadeStages.length === 0 && (
              <AddButton onClick={() => setWeights([...weights, { stage_id: "", weight: 0.5, is_gate: false }])}>
                添加阶段权重
              </AddButton>
            )}
            <Field label="策略 id" optional hint="聚合策略标识，可空">
              <Input className="font-mono text-xs" value={policy.id ?? ""} onChange={(e) => onChange({ ...policy, id: e.target.value })} />
            </Field>
          </>
        ) : (
          <>
            <p className="text-[11px] text-muted-foreground">YAML 模式可编辑完整聚合策略；发布以当前解析结构为准。</p>
            <Textarea className="min-h-[300px] font-mono text-xs leading-relaxed" value={yamlText} onChange={(e) => onYamlChange(e.target.value)} />
          </>
        )}
        <p className="text-[11px] text-muted-foreground">编辑后在右侧「版本时间线」发布新版本。</p>
      </SectionCardContent>
    </SectionCard>
      <AiResultDialog
        open={aiOpen}
        loading={aiLoading}
        title="✨ AI 生成聚合策略"
        description="基于场景级联阶段 + 指标定义生成聚合策略"
        onAccept={aiPolicy ? acceptAiPolicy : undefined}
        onCancel={() => {
          setAiOpen(false)
          setAiPolicy(null)
        }}
      >
        {aiPolicy && (
          <div>
            <p className="mb-1 font-semibold text-foreground">生成结果（点击采纳覆盖当前策略）</p>
            <pre className="whitespace-pre-wrap rounded bg-background p-2 font-mono text-[11px]">{JSON.stringify(aiPolicy, null, 2)}</pre>
          </div>
        )}
      </AiResultDialog>
    </>
  )
}
