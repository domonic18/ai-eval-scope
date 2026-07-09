import { useEffect, useMemo, useState } from "react"
import { useParams } from "react-router-dom"
import { api } from "../api/client"
import type { ArtifactRow, ConstraintRow } from "../types"
import { fmt3 } from "../lib/format"
import { METRIC_LABEL, SCORE_EXPLAIN, STAGES } from "../lib/eval"
import { Button } from "@/components/shadcn/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/shadcn/select"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/shadcn/tooltip"
import { useCrumbs } from "../components/AppShell"
import { useToast } from "../components/toast"
import { SemPill, TierChip } from "../components/shared"
import { ChevronRight, ExternalLink, HelpCircle } from "lucide-react"

interface SampleData {
  id: string
  externalSampleId: string
  status: string
  reward: number
  constraintResults: ConstraintRow[]
  artifacts: ArtifactRow[]
}

type PreviewMode = "iframe" | "img" | "text" | "none"
interface PreviewState {
  mode: PreviewMode
  url?: string
  text?: string
}
type PrevTab = "doc" | "shot" | "trace"

function avg(nums: number[]): number | undefined {
  if (nums.length === 0) return undefined
  return nums.reduce((a, b) => a + b, 0) / nums.length
}

export default function SampleDetail() {
  const { id, sid } = useParams<{ id: string; sid: string }>()
  const { setCrumbs } = useCrumbs()
  const toast = useToast()
  const [sample, setSample] = useState<SampleData | null>(null)

  useEffect(() => {
    if (!id || !sid) return
    api.sampleDetail(id, sid).then((s) => {
      setSample(s)
      setCrumbs([
        { label: "项目看板", to: "/dashboard" },
        { label: "运行", to: `/run/${id}` },
        { label: s.externalSampleId },
      ])
    }).catch(() => setSample(null))
  }, [id, sid, setCrumbs])

  const stageScores = useMemo(() => {
    const cs = sample?.constraintResults ?? []
    const byTier = (t: string) => cs.filter((c) => c.tier === t)
    const fmt = byTier("hard_gate")
    const com = byTier("hard_score")
    const soft = byTier("soft")
    const pref = byTier("preference")
    return {
      sFormat: fmt.length ? (fmt.every((c) => c.passed) ? 1 : -3) : undefined,
      sCommon: com.length ? (com.every((c) => c.passed) ? 1 : 0) : undefined,
      sSoft: avg(soft.map((c) => c.score)),
      sPref: avg(pref.map((c) => c.score)),
    }
  }, [sample])

  if (!sample) return <div className="p-8 text-muted-foreground">加载样本详情…</div>

  const failedCount = sample.constraintResults.filter((c) => !c.passed).length

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      {/* 样本摘要条 */}
      <div className="flex items-center justify-between border-b px-6 py-3">
        <div className="flex items-center gap-2.5">
          <span className="font-mono text-sm font-semibold">{sample.externalSampleId}</span>
          <SemPill tone={sample.status === "pass" || sample.status === "passed" ? "success" : "danger"}>
            {sample.status}
          </SemPill>
          <SemPill tone="neutral">
            {METRIC_LABEL.Reward}
            <b className="ml-1 font-mono text-[var(--danger)]">{fmt3(sample.reward)}</b>
          </SemPill>
          {failedCount > 0 && (
            <SemPill tone="danger" dot>
              {failedCount} 项约束失败
            </SemPill>
          )}
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => toast.info("请在运行详情的样本表中切换样本")}>上一个</Button>
          <Button size="sm" variant="outline" onClick={() => toast.info("请在运行详情的样本表中切换样本")}>下一个</Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-2">
        {/* 左：约束结论 */}
        <div className="overflow-y-auto border-r p-6">
          <TooltipProvider delayDuration={200}>
            {STAGES.map((stage) => {
              const constraints = sample.constraintResults.filter((c) => stage.tiers.includes(c.tier))
              if (constraints.length === 0) return null
              return (
                <div key={stage.key} className="mb-6">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="h-3 w-1 rounded-full" style={{ background: stage.bar }} />
                    <h3 className="text-sm font-semibold">{stage.title}</h3>
                    {stage.chips.map((ch) => (
                      <TierChip key={ch.label} tier={ch.chip}>
                        {ch.label}
                      </TierChip>
                    ))}
                    {stage.scoreExplainKey && (
                      <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
                        {stage.scoreText?.(stageScores)}
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <HelpCircle className="size-3.5 cursor-help" />
                          </TooltipTrigger>
                          <TooltipContent>
                            {(() => {
                              const ex = SCORE_EXPLAIN[stage.scoreExplainKey]
                              return (
                                <div className="max-w-[220px] space-y-1">
                                  <div className="font-medium">{ex.title}</div>
                                  {ex.rows.map((r, i) => (
                                    <div key={i} className="text-xs">
                                      <span className="font-mono">{r.dt}</span>：{r.dd}
                                    </div>
                                  ))}
                                </div>
                              )
                            })()}
                          </TooltipContent>
                        </Tooltip>
                      </span>
                    )}
                  </div>
                  <div className="space-y-1">
                    {constraints.map((c) => (
                      <ConstraintItem key={c.id} c={c} />
                    ))}
                  </div>
                </div>
              )
            })}
            {sample.constraintResults.length === 0 && (
              <div className="py-8 text-center text-sm text-muted-foreground">无约束结果</div>
            )}
          </TooltipProvider>
        </div>

        {/* 右：制品预览 */}
        <div className="flex min-h-0 flex-col">
          <PreviewPane
            artifacts={sample.artifacts}
            isMultimodal={sample.constraintResults.some((c) => c.constraintId?.includes("vision"))}
          />
        </div>
      </div>
    </div>
  )
}

function ConstraintItem({ c }: { c: ConstraintRow }) {
  const [open, setOpen] = useState(!c.passed)
  const method = c.judgeProvider ? "LLM_JUDGE" : "RULE"
  return (
    <div className={`rounded-md border ${!c.passed ? "border-red-500/30 bg-red-500/5" : "border-border"}`}>
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm">
        {c.passed ? (
          <SemPill tone="success">PASS</SemPill>
        ) : (
          <SemPill tone="danger">FAIL</SemPill>
        )}
        <span className="flex-1 truncate">
          {c.name}
          <span className="ml-2 font-mono text-[10px] text-muted-foreground">{c.constraintId}</span>
        </span>
        <span className={`font-mono text-xs tabular-nums ${c.passed ? "text-emerald-400" : "text-red-400"}`}>{c.score.toFixed(2)}</span>
        <ChevronRight className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <div className="space-y-2 border-t px-3 py-2 text-xs">
          {c.reason && <div className="text-muted-foreground">{c.reason}</div>}
          <DimensionBreakdown details={c.details} />
          {constraintErrors(c.details).length > 0 && (
            <div className="rounded border border-red-500/20 bg-red-500/5 p-2">
              <div className="mb-1 font-medium text-red-400">发现的问题</div>
              <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
                {constraintErrors(c.details).map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
            <span><b className="text-foreground">方法</b> {method}</span>
            {c.judgeProvider && <span><b className="text-foreground">Judge</b> {c.judgeProvider}/{c.judgeModel ?? "?"}</span>}
            <span><b className="text-foreground">耗时</b> {Math.round(c.durationMs)}ms</span>
            {c.tier !== "hard_gate" && c.tier !== "hard_score" && <span><b className="text-foreground">层级</b> {c.tier}</span>}
          </div>
          {hasDebug(c) && (
            <details className="pt-1">
              <summary className="cursor-pointer text-muted-foreground">调试详情（技术细节）</summary>
              <div className="mt-1 space-y-2">
                {c.details && Object.keys(c.details).length > 0 && <pre className="overflow-x-auto rounded bg-muted/50 p-2 text-[11px]">{JSON.stringify(c.details, null, 2)}</pre>}
                {c.moduleResults && Object.keys(c.moduleResults).length > 0 && <pre className="overflow-x-auto rounded bg-muted/50 p-2 text-[11px]">{JSON.stringify(c.moduleResults, null, 2)}</pre>}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

/** 质量（soft/preference）约束的逐维度评分 + 扣分原因渲染。
 *  读 details.dimensions[]（每项含 score/band/reason/issues/highlights），由评估器
 *  从 LLM 结构化输出透传（docs/arch/14 §五）。硬约束无此结构 → 不渲染。 */
interface DimensionIssue {
  desc: string
  severity?: "high" | "medium" | "low"
  evidence?: string
}
interface DimensionDetail {
  id?: string
  name?: string
  score?: number
  band?: string
  confidence?: string
  reason?: string
  issues?: DimensionIssue[]
  highlights?: string[]
}

function bandTone(band: string): string {
  if (band === "优秀" || band === "良好") return "text-emerald-400"
  if (band === "合格") return "text-amber-400"
  return "text-red-400"
}
function severityTone(sev?: string): string {
  if (sev === "high") return "text-red-400"
  if (sev === "medium") return "text-amber-400"
  return "text-muted-foreground"
}

function DimensionBreakdown({ details }: { details: Record<string, unknown> | null }) {
  const dims = details?.dimensions
  if (!Array.isArray(dims) || dims.length === 0) return null
  return (
    <div className="space-y-1.5">
      {(dims as DimensionDetail[]).map((d, i) => {
        const issues = Array.isArray(d.issues) ? d.issues : []
        const highlights = Array.isArray(d.highlights) ? d.highlights : []
        return (
          <div key={d.id ?? i} className="rounded border border-border bg-background/40 p-2">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="font-medium text-foreground">{d.name ?? d.id}</span>
              <span className="font-mono tabular-nums text-muted-foreground">
                {d.score != null ? d.score.toFixed(1) : "—"}/10
              </span>
              {d.band && <span className={`font-medium ${bandTone(d.band)}`}>{d.band}</span>}
              {d.confidence === "low" && (
                <span className="text-[10px] text-amber-400">置信度低</span>
              )}
            </div>
            {d.reason && <div className="mt-1 text-muted-foreground">{d.reason}</div>}
            {issues.length > 0 && (
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {issues.map((it, j) => (
                  <li key={j}>
                    <span className={severityTone(it.severity)}>{it.desc}</span>
                    {it.evidence && <span className="text-muted-foreground"> — {it.evidence}</span>}
                  </li>
                ))}
              </ul>
            )}
            {highlights.length > 0 && (
              <div className="mt-1 text-emerald-400">亮点：{highlights.join("；")}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function constraintErrors(details: Record<string, unknown> | null): string[] {
  if (!details) return []
  const e = details.errors
  if (!Array.isArray(e)) return []
  return e.filter((x): x is string => typeof x === "string")
}
function hasDebug(c: ConstraintRow): boolean {
  return (!!c.details && Object.keys(c.details).length > 0) || (!!c.moduleResults && Object.keys(c.moduleResults).length > 0)
}

function PreviewPane({ artifacts, isMultimodal }: { artifacts: ArtifactRow[]; isMultimodal: boolean }) {
  const [tab, setTab] = useState<PrevTab>("doc")
  const [preview, setPreview] = useState<PreviewState>({ mode: "none" })
  const [loading, setLoading] = useState(false)

  const groups = useMemo(() => {
    const isHtml = (a: ArtifactRow) => a.contentType.includes("html") || a.kind === "output"
    const isImg = (a: ArtifactRow) => a.contentType.startsWith("image") || a.kind === "screenshot"
    const isTrace = (a: ArtifactRow) => a.kind === "trace" || a.contentType.includes("json") || a.kind === "judge_record"
    return { doc: artifacts.filter(isHtml), shot: artifacts.filter(isImg), trace: artifacts.filter(isTrace) }
  }, [artifacts])

  const docArts = useMemo(() => {
    const used = new Set([...groups.shot, ...groups.trace].map((a) => a.id))
    return artifacts.filter((a) => !used.has(a.id))
  }, [artifacts, groups])

  const listFor = (t: PrevTab): ArtifactRow[] => (t === "doc" ? docArts : t === "shot" ? groups.shot : groups.trace)
  const [selectedId, setSelectedId] = useState<Record<PrevTab, string>>({ doc: "", shot: "", trace: "" })

  const currentList = listFor(tab)
  const currentId = selectedId[tab] || currentList[0]?.id || ""
  const current = currentList.find((a) => a.id === currentId) || currentList[0]

  useEffect(() => {
    setSelectedId({ doc: docArts[0]?.id || "", shot: groups.shot[0]?.id || "", trace: groups.trace[0]?.id || "" })
  }, [docArts, groups.shot, groups.trace])

  useEffect(() => {
    let cancelled = false
    if (!current) {
      setPreview({ mode: "none" })
      return
    }
    setLoading(true)
    api.artifactPreview(current.id).then(async (p) => {
      if (cancelled) return
      if (p.contentType.includes("html")) setPreview({ mode: "iframe", url: p.url })
      else if (p.contentType.startsWith("image")) setPreview({ mode: "img", url: p.url })
      else {
        try {
          const resp = await fetch(p.url)
          setPreview({ mode: "text", text: await resp.text() })
        } catch {
          setPreview({ mode: "text", text: "（无法加载文件内容）" })
        }
      }
    }).catch(() => !cancelled && setPreview({ mode: "text", text: "（无法加载文件内容）" })).finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [current])

  const tabs: [PrevTab, string][] = [["doc", "原始文档"], ...(isMultimodal ? [["shot", "渲染截图"] as [PrevTab, string]] : []), ["trace", "执行 Trace"]]
  const hasAny = artifacts.length > 0

  return (
    <>
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex rounded-md border p-0.5">
          {tabs.map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)} className={`rounded px-2.5 py-1 text-xs transition-colors ${tab === k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {currentList.length > 0 && (
            <Select value={currentId} onValueChange={(v) => setSelectedId((s) => ({ ...s, [tab]: v }))}>
              <SelectTrigger className="h-7 w-48 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {currentList.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.originalName || a.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {current && (
            <a className="inline-flex size-7 items-center justify-center rounded-md hover:bg-accent" href={api.artifactUrl(current.id)} target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" />
            </a>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto bg-inset p-4">
        {!hasAny ? (
          <div className="py-8 text-center text-sm text-muted-foreground">该样本暂无可预览的产出物。</div>
        ) : !current ? (
          <div className="py-8 text-center text-sm text-muted-foreground">暂无{tab === "doc" ? "原始文档" : tab === "shot" ? "渲染截图" : "执行 Trace"}制品</div>
        ) : loading ? (
          <div className="py-8 text-center text-sm text-muted-foreground">加载中…</div>
        ) : preview.mode === "iframe" ? (
          <iframe src={preview.url} className="h-[70vh] w-full rounded-lg border bg-white" title="preview" />
        ) : preview.mode === "img" ? (
          <div className="mx-auto max-w-2xl">
            <img src={preview.url} alt="screenshot" className="w-full rounded-lg border" />
          </div>
        ) : (
          <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg border bg-background p-4 text-xs text-muted-foreground">
            {preview.text}
          </pre>
        )}
      </div>
    </>
  )
}
