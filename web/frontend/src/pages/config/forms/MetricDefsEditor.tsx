/**
 * 场景默认指标定义编辑器（表单 + YAML 切换）。
 * 直接 PATCH Scenario.defaultMetricDefinitions（场景级默认值，非版本化资产）。
 */
import { useEffect, useState } from "react"
import * as yaml from "js-yaml"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Textarea } from "../../../components/shadcn/textarea"
import { Save, Sparkles, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { extractErr } from "../../../hooks/useAiGeneration"
import { api } from "../../../api/client"
import type { MetricDef } from "../../../types"
import { AddButton, SectionCard, SectionCardContent, SectionCardHeader, SectionCardTitle } from "../../../components/shared"
import { AiResultDialog } from "../../../components/AiResultDialog"
import { Field, FormYamlToggle } from "./Field"

const errMsg = (e: unknown) => extractErr(e, "保存失败")

export function MetricDefsEditor({ scenarioId }: { scenarioId: string }) {
  const [metrics, setMetrics] = useState<MetricDef[]>([])
  const [yamlText, setYamlText] = useState("")
  const [mode, setMode] = useState<"form" | "yaml">("form")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  // AI 生成（hook 必须在 early return 之前，避免 hooks 顺序违规）
  const [aiOpen, setAiOpen] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiDesc, setAiDesc] = useState("")
  const [aiMetrics, setAiMetrics] = useState<MetricDef[]>([])

  useEffect(() => {
    api
      .scenarioDefaults(scenarioId)
      .then((m) => {
        setMetrics(m)
        setYamlText(yaml.dump(m, { sortKeys: false }))
      })
      .catch(() => {
        setMetrics([])
        setYamlText("[]")
      })
      .finally(() => setLoading(false))
  }, [scenarioId])

  const syncYaml = (m: MetricDef[]) => setYamlText(yaml.dump(m, { sortKeys: false }))
  const update = (i: number, patch: Partial<MetricDef>) => {
    const arr = [...metrics]
    arr[i] = { ...arr[i], ...patch }
    setMetrics(arr)
    syncYaml(arr)
  }
  const add = () => {
    const arr = [...metrics, { id: "" }]
    setMetrics(arr)
    syncYaml(arr)
  }
  const remove = (i: number) => {
    const arr = metrics.filter((_, j) => j !== i)
    setMetrics(arr)
    syncYaml(arr)
  }
  const onYamlChange = (text: string) => {
    setYamlText(text)
    try {
      const parsed = yaml.load(text)
      if (Array.isArray(parsed)) setMetrics(parsed as MetricDef[])
    } catch {
      /* YAML 语法错误时保留编辑 */
    }
  }
  const switchMode = (m: "form" | "yaml") => {
    if (m === "yaml") setYamlText(yaml.dump(metrics, { sortKeys: false }))
    setMode(m)
  }
  const save = async () => {
    setBusy(true)
    try {
      await api.updateScenarioDefaults(scenarioId, { metricDefinitions: metrics })
      toast.success("指标定义已保存")
    } catch (e) {
      toast.error(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <SectionCard>
        <SectionCardContent className="py-10 text-center text-sm text-muted-foreground">加载中…</SectionCardContent>
      </SectionCard>
    )
  }

  async function runAiGenerate() {
    if (!aiDesc.trim()) {
      toast.error("请先填写评估目标描述")
      return
    }
    setAiLoading(true)
    try {
      const r = await api.aiGenerateMetrics({ scenario: scenarioId, description: aiDesc })
      setAiMetrics(r.metricDefinitions as unknown as MetricDef[])
    } catch (e) {
      toast.error(extractErr(e, "AI 生成失败"))
    } finally {
      setAiLoading(false)
    }
  }
  function acceptAiMetrics() {
    setMetrics([...metrics, ...aiMetrics])
    syncYaml([...metrics, ...aiMetrics])
    setAiOpen(false)
    setAiDesc("")
    setAiMetrics([])
    toast.success(`已采纳 ${aiMetrics.length} 项 AI 生成的指标`)
  }

  return (
    <>
    <SectionCard>
      <SectionCardHeader className="flex-row items-center justify-between">
        <SectionCardTitle>指标定义（场景默认）</SectionCardTitle>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setAiOpen(true)}>
            <Sparkles className="mr-1 size-3.5" /> AI 生成
          </Button>
          <FormYamlToggle mode={mode} onChange={switchMode} />
        </div>
      </SectionCardHeader>
      <SectionCardContent className="space-y-3">
        {mode === "form" ? (
          <>
            {metrics.map((d, i) => (
              <div key={i} className="rounded-md border p-2">
                <div className="flex items-start gap-2">
                  <div className="grid flex-1 grid-cols-2 gap-2">
                    <Field label="id" required hint="指标唯一标识，如 DR / CPR">
                      <Input className="font-mono text-xs" value={d.id} onChange={(e) => update(i, { id: e.target.value })} />
                    </Field>
                    <Field label="名称" optional hint="人类可读名称">
                      <Input value={d.name ?? ""} onChange={(e) => update(i, { name: e.target.value })} />
                    </Field>
                    <Field label="expression" optional hint="计算表达式 / 取值路径">
                      <Input className="font-mono text-xs" value={d.expression ?? ""} onChange={(e) => update(i, { expression: e.target.value })} />
                    </Field>
                    <Field label="unit" optional hint="单位，如 % / 分">
                      <Input value={d.unit ?? ""} onChange={(e) => update(i, { unit: e.target.value })} />
                    </Field>
                    <Field label="threshold" optional hint="达标阈值（数值，可空）">
                      <Input
                        type="number"
                        value={d.threshold ?? ""}
                        onChange={(e) => update(i, { threshold: e.target.value === "" ? null : Number(e.target.value) })}
                      />
                    </Field>
                    <div className="col-span-2">
                      <Field label="说明（大白话）" optional hint="摘要报告用的一句话描述；详细 explain 请切 YAML 模式">
                        <Input
                          value={d.summary ?? ""}
                          onChange={(e) => update(i, { summary: e.target.value })}
                          placeholder="如：所有样本的格式是否合规"
                        />
                      </Field>
                    </div>
                  </div>
                  <Button size="sm" variant="ghost" className="mt-5 text-red-400" onClick={() => remove(i)}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </div>
            ))}
            <AddButton onClick={add}>添加指标</AddButton>
          </>
        ) : (
          <>
            <p className="text-[11px] text-muted-foreground">
              YAML 模式可编辑全部字段（含 explain 等深层结构）；保存以当前解析结构为准。
            </p>
            <Textarea
              className="min-h-[360px] font-mono text-xs leading-relaxed"
              value={yamlText}
              onChange={(e) => onYamlChange(e.target.value)}
            />
          </>
        )}
        <Button onClick={save} disabled={busy}>
          <Save className="mr-1 size-4" />{busy ? "保存中…" : "保存"}
        </Button>
      </SectionCardContent>
    </SectionCard>
      <AiResultDialog
        open={aiOpen}
        loading={aiLoading}
        title="✨ AI 生成指标定义"
        description="填写评估目标描述，生成可量化指标"
        onAccept={aiMetrics.length > 0 ? acceptAiMetrics : undefined}
        onCancel={() => {
          setAiOpen(false)
          setAiMetrics([])
        }}
      >
        <div className="space-y-3">
          <div>
            <p className="mb-1 font-semibold text-foreground">评估目标描述</p>
            <Textarea
              className="min-h-[80px]"
              value={aiDesc}
              onChange={(e) => setAiDesc(e.target.value)}
              placeholder="如：评估课件生成的事实正确性、格式合规性与教学逻辑质量"
            />
            <Button size="sm" className="mt-2" onClick={runAiGenerate} disabled={aiLoading}>
              {aiLoading ? "生成中…" : "生成"}
            </Button>
          </div>
          {aiMetrics.length > 0 && (
            <div>
              <p className="mb-1 font-semibold text-foreground">生成结果（点击采纳追加）</p>
              <pre className="whitespace-pre-wrap rounded bg-background p-2 font-mono text-[11px]">{JSON.stringify(aiMetrics, null, 2)}</pre>
            </div>
          )}
        </div>
      </AiResultDialog>
    </>
  )
}
