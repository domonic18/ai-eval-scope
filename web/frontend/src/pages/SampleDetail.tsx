import { useEffect, useMemo, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"
import { CodeBlock } from "../components/CodeBlock"
import { useParams } from "react-router-dom"
import { api } from "../api/client"
import type { ArtifactRow, ConstraintRow } from "../types"
import { fmt3 } from "../lib/format"
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
import { useCrumbs } from "../context/navigation"
import { useToast } from "../hooks/useToast"
import { SemPill, TierChip, type Tier } from "../components/shared"
import { ChevronRight, ExternalLink, FileText, HelpCircle } from "lucide-react"

/** 约束层级（evaluator 全局 ConstraintTier）→ 展示语义（场景无关）。 */
interface TierGroupDef {
  tier: string
  title: string
  chip: Tier
  bar: string
  explain: string
}
const TIER_GROUPS: TierGroupDef[] = [
  {
    tier: "hard_gate",
    title: "门禁约束",
    chip: "hard",
    bar: "var(--danger)",
    explain: "硬门禁（HARD_GATE）：任一约束失败即 fail-fast，终止后续阶段评估。",
  },
  {
    tier: "hard_score",
    title: "硬性约束",
    chip: "hard",
    bar: "var(--danger)",
    explain: "硬性约束（HARD_SCORE）：失败不中断同阶段其它评估，但记 0 分并标记门禁未过。",
  },
  {
    tier: "soft",
    title: "软约束",
    chip: "soft",
    bar: "var(--warning)",
    explain: "软约束（SOFT）：各评估器打分加权平均，归一化到 [0,1]，按权重计入综合分。",
  },
  {
    tier: "preference",
    title: "偏好约束",
    chip: "pref",
    bar: "var(--info)",
    explain: "偏好约束（PREFERENCE）：主观偏好维度加权平均，归一化到 [0,1]，按权重计入综合分。",
  },
]
const TIER_LABEL: Record<string, string> = {
  hard_gate: "HARD_GATE",
  hard_score: "HARD_SCORE",
  soft: "SOFT",
  preference: "PREFERENCE",
}

interface SampleData {
  id: string
  externalSampleId: string
  status: string
  reward: number
  constraintResults: ConstraintRow[]
  artifacts: ArtifactRow[]
}

type PreviewMode = "iframe" | "img" | "markdown" | "json" | "text" | "none"
interface PreviewState {
  mode: PreviewMode
  url?: string
  text?: string
}
type PrevTab = "doc" | "shot" | "trace"

/** 文件定位（约束→源课件文件），评估器产出 details.source_files（docs/arch/13）。 */
interface SourceFile {
  filename: string
  artifact_kind?: string
  page?: number
  snippet?: string
}

/** 制品归属的预览 tab（与 PreviewPane 分组一致）。 */
function artifactTab(a: ArtifactRow): PrevTab {
  if (a.kind === "trace" || a.contentType.includes("json") || a.kind === "judge_record") return "trace"
  if (a.contentType.startsWith("image") || a.kind === "screenshot") return "shot"
  return "doc"
}

/** 按 filename 匹配 sample 制品：精确 originalName → 尾缀（相对路径）→ basename。 */
function matchArtifactByFilename(artifacts: ArtifactRow[], filename: string): ArtifactRow | null {
  const f = filename.trim()
  if (!f) return null
  const norm = (s: string) => s.replace(/\\/g, "/").toLowerCase()
  const target = norm(f)
  const base = target.split("/").pop() || target
  const cands = artifacts.filter((a) => a.originalName)
  return (
    cands.find((a) => norm(a.originalName!) === target) ||
    cands.find((a) => {
      const n = norm(a.originalName!)
      return n.endsWith("/" + target) || n.endsWith(target)
    }) ||
    cands.find((a) => {
      const ob = norm(a.originalName!).split("/").pop() || ""
      return ob === base
    }) ||
    null
  )
}

/** 从约束 details 解析 source_files（容错：历史数据无此字段返回空）。 */
function parseSourceFiles(details: Record<string, unknown> | null): SourceFile[] {
  const s = details?.source_files
  if (!Array.isArray(s)) return []
  return s
    .filter((x): x is Record<string, unknown> => !!x && typeof x === "object")
    .map((x) => ({
      filename: String(x.filename ?? "").trim(),
      artifact_kind: typeof x.artifact_kind === "string" ? x.artifact_kind : undefined,
      page: typeof x.page === "number" ? x.page : undefined,
      snippet: typeof x.snippet === "string" ? x.snippet : undefined,
    }))
    .filter((x) => x.filename.length > 0)
}

export default function SampleDetail() {
  const { id, sid } = useParams<{ id: string; sid: string }>()
  const { setCrumbs } = useCrumbs()
  const toast = useToast()
  const [sample, setSample] = useState<SampleData | null>(null)
  // 制品预览受控状态（docs/arch/13 §4.4）：状态上提，供扣分项文件 chip 联动驱动
  const [previewTab, setPreviewTab] = useState<PrevTab>("doc")
  const [previewSelected, setPreviewSelected] = useState<Record<PrevTab, string>>({
    doc: "",
    shot: "",
    trace: "",
  })
  const handleSelectFile = (a: ArtifactRow) => {
    const t = artifactTab(a)
    setPreviewTab(t)
    setPreviewSelected((prev) => ({ ...prev, [t]: a.id }))
  }

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

  /** 按 tier 分组的约束统计（全过/未过数 + 均分），场景无关。 */
  const tierStats = useMemo(() => {
    const cs = sample?.constraintResults ?? []
    const stats: Record<string, { total: number; passed: number; avg?: number }> = {}
    for (const g of TIER_GROUPS) {
      const rows = cs.filter((c) => c.tier === g.tier)
      if (rows.length === 0) continue
      const scores = rows.map((c) => c.score)
      stats[g.tier] = {
        total: rows.length,
        passed: rows.filter((c) => c.passed).length,
        avg: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : undefined,
      }
    }
    return stats
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
            综合评分
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
            {TIER_GROUPS.map((group) => {
              const constraints = sample.constraintResults.filter((c) => c.tier === group.tier)
              if (constraints.length === 0) return null
              const stat = tierStats[group.tier]
              return (
                <div key={group.tier} className="mb-6">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="h-3 w-1 rounded-full" style={{ background: group.bar }} />
                    <h3 className="text-sm font-semibold">{group.title}</h3>
                    <TierChip tier={group.chip}>{TIER_LABEL[group.tier]}</TierChip>
                    <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
                      {stat && (
                        <span className="font-mono">
                          {group.tier === "soft" || group.tier === "preference"
                            ? `均分 ${stat.avg != null ? stat.avg.toFixed(2) : "—"}`
                            : `${stat.passed}/${stat.total} 通过`}
                        </span>
                      )}
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <HelpCircle className="size-3.5 cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent>
                          <div className="max-w-[220px] text-xs">{group.explain}</div>
                        </TooltipContent>
                      </Tooltip>
                    </span>
                  </div>
                  <div className="space-y-1">
                    {constraints.map((c) => (
                      <ConstraintItem
                        key={c.id}
                        c={c}
                        artifacts={sample.artifacts}
                        activeFileId={previewSelected[previewTab]}
                        onSelectFile={handleSelectFile}
                      />
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
            tab={previewTab}
            onTabChange={setPreviewTab}
            selectedId={previewSelected}
            onSelectId={(t, id) => setPreviewSelected((prev) => ({ ...prev, [t]: id }))}
          />
        </div>
      </div>
    </div>
  )
}

function ConstraintItem({
  c,
  artifacts,
  activeFileId,
  onSelectFile,
}: {
  c: ConstraintRow
  artifacts: ArtifactRow[]
  activeFileId: string
  onSelectFile: (a: ArtifactRow) => void
}) {
  const [open, setOpen] = useState(!c.passed)
  const method = c.judgeProvider ? "LLM_JUDGE" : "RULE"
  const sourceFiles = parseSourceFiles(c.details)
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
          {sourceFiles.length > 0 && (
            <SourceFileChips
              files={sourceFiles}
              artifacts={artifacts}
              activeFileId={activeFileId}
              onSelectFile={onSelectFile}
            />
          )}
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
          {c.moduleResults && c.moduleResults.length > 0 && <ModuleResultsTable modules={c.moduleResults} />}
          {hasDebug(c) && (
            <details className="pt-1">
              <summary className="cursor-pointer text-muted-foreground">调试详情（技术细节）</summary>
              <div className="mt-1 space-y-2">
                {c.details && Object.keys(c.details).length > 0 && <pre className="overflow-x-auto rounded bg-muted/50 p-2 text-[11px]">{JSON.stringify(c.details, null, 2)}</pre>}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

/** 约束的「涉及文件」chip 行（docs/arch/13）：点击命中制品 → 右侧预览联动切换。
 *  无 source_files 的历史数据不渲染（降级）。 */
function SourceFileChips({
  files,
  artifacts,
  activeFileId,
  onSelectFile,
}: {
  files: SourceFile[]
  artifacts: ArtifactRow[]
  activeFileId: string
  onSelectFile: (a: ArtifactRow) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-muted-foreground">涉及文件：</span>
      {files.map((sf, i) => {
        const hit = matchArtifactByFilename(artifacts, sf.filename)
        const active = !!hit && hit.id === activeFileId
        return (
          <button
            key={i}
            type="button"
            disabled={!hit}
            onClick={() => hit && onSelectFile(hit)}
            title={hit ? `点击在右侧预览 ${sf.filename}` : `${sf.filename}（未找到对应制品）`}
            className={`inline-flex max-w-[240px] items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] transition-colors ${
              active
                ? "border-primary bg-primary/20 text-primary"
                : hit
                  ? "cursor-pointer border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
                  : "cursor-not-allowed border-border text-muted-foreground/50 line-through"
            }`}
          >
            <FileText className="size-3 shrink-0" />
            <span className="truncate">{sf.filename}</span>
          </button>
        )
      })}
    </div>
  )
}

/** 质量（soft/preference）约束的逐维度评分 + 扣分原因渲染。
 *  读 details.dimensions[]（每项含 score/band/reason/issues/highlights），由评估器
 *  从 LLM 结构化输出透传（docs/arch/13 §五）。硬约束无此结构 → 不渲染。 */
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
  return !!c.details && Object.keys(c.details).length > 0
}

/** 目录模式（大单元）模块级评估结果表（docs/arch/04 §5.5.3）。 */
function ModuleResultsTable({ modules }: { modules: Array<Record<string, unknown>> }) {
  return (
    <div className="mt-2 overflow-x-auto rounded border border-border">
      <table className="w-full text-[11px]">
        <thead className="bg-muted/50 text-muted-foreground">
          <tr>
            <th className="px-2 py-1 text-left">模块</th>
            <th className="px-2 py-1 text-right">文件数</th>
            <th className="px-2 py-1 text-right">得分</th>
            <th className="px-2 py-1 text-center">通过</th>
            <th className="px-2 py-1 text-left">原因</th>
          </tr>
        </thead>
        <tbody>
          {modules.map((m, i) => {
            const score = typeof m.score === "number" ? m.score : null
            return (
              <tr key={i} className="border-t border-border/50">
                <td className="px-2 py-1">{String(m.module ?? "?")}</td>
                <td className="px-2 py-1 text-right">{String(m.file_count ?? "-")}</td>
                <td className={`px-2 py-1 text-right font-medium ${scoreColor(score)}`}>
                  {score !== null ? score.toFixed(2) : "-"}
                </td>
                <td className="px-2 py-1 text-center">{m.passed === true ? "✓" : "✗"}</td>
                <td className="px-2 py-1 text-muted-foreground">{String(m.reason ?? "")}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function scoreColor(score: number | null): string {
  if (score === null) return ""
  if (score >= 0.7) return "text-green-600"
  if (score >= 0.4) return "text-yellow-600"
  return "text-red-600"
}

function PreviewPane({
  artifacts,
  isMultimodal,
  tab,
  onTabChange,
  selectedId,
  onSelectId,
}: {
  artifacts: ArtifactRow[]
  isMultimodal: boolean
  tab: PrevTab
  onTabChange: (t: PrevTab) => void
  selectedId: Record<PrevTab, string>
  onSelectId: (t: PrevTab, id: string) => void
}) {
  const [preview, setPreview] = useState<PreviewState>({ mode: "none" })
  const [loading, setLoading] = useState(false)

  const groups = useMemo(() => {
    const shot = artifacts.filter((a) => artifactTab(a) === "shot")
    const trace = artifacts.filter((a) => artifactTab(a) === "trace")
    const used = new Set([...shot, ...trace].map((a) => a.id))
    const doc = artifacts.filter((a) => !used.has(a.id))
    return { doc, shot, trace }
  }, [artifacts])

  const listFor = (t: PrevTab): ArtifactRow[] =>
    t === "doc" ? groups.doc : t === "shot" ? groups.shot : groups.trace

  const currentList = listFor(tab)
  const currentId = selectedId[tab] || currentList[0]?.id || ""
  const current = currentList.find((a) => a.id === currentId) || currentList[0]

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
          const text = await resp.text()
          if (p.contentType.includes("markdown")) setPreview({ mode: "markdown", text })
          else if (p.contentType.includes("json")) setPreview({ mode: "json", text })
          else setPreview({ mode: "text", text })
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
            <button key={k} onClick={() => onTabChange(k)} className={`rounded px-2.5 py-1 text-xs transition-colors ${tab === k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {currentList.length > 0 && (
            <Select value={currentId} onValueChange={(v) => onSelectId(tab, v)}>
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
        ) : preview.mode === "markdown" ? (
          <article className="mx-auto max-w-3xl rounded-lg border bg-background p-6 text-sm leading-relaxed [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:text-lg [&_h2]:font-semibold [&_p]:mb-2 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-inset [&_pre]:p-3 [&_code]:font-mono [&_code]:text-xs [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:mb-1 [&_strong]:font-semibold">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
              {preview.text ?? ""}
            </ReactMarkdown>
          </article>
        ) : preview.mode === "json" ? (
          <div className="mx-auto max-w-4xl">
            <CodeBlock title={current?.originalName || "JSON"} code={preview.text ?? ""} />
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
