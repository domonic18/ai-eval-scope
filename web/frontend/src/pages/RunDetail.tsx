import { useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { api } from "../api/client"
import { fmt3, fmtMsRaw, num } from "../lib/format"
import { DynamicMetricGrid } from "../components/DynamicMetricGrid"
import { extractMetricDefs } from "../lib/metricGrid"
import { useScenarioDefaults } from "../hooks/useScenarioDefaults"
import { Button } from "@/components/shadcn/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import { SectionCard, SectionCardContent, SectionCardHeader, SectionCardTitle } from "../components/shared"
import { useCrumbs } from "../context/navigation"
import { useToast } from "../hooks/useToast"
import { Page, PageHead, StatusBadge } from "../components/shared"
import type { MetricDef } from "../types"
import { ChevronRight, Download, ExternalLink, FileText, Trash2 } from "lucide-react"

interface SampleRow {
  id: string
  externalSampleId: string
  status: string
  reward: number
}
interface RunData {
  id: string
  externalRunId: string
  projectId: string
  canDelete: boolean
  mode: string
  status: string
  totalSamples: number
  metrics?: Record<string, number>
  scenarioId?: string | null
  runConfigSnapshot?: { content: Record<string, unknown>; contentHash: string } | null
  ruleSetVersion: string | null
  langfuseTraceId: string | null
  langfuseHost: string | null
  createdAt: string
  samples: SampleRow[]
}
interface OverviewData {
  verdict?: "pass" | "fail"
  score?: number
  metrics?: Record<string, number>
  metrics_raw?: Record<string, number>
  summary?: { total: number; passed: number; failed: number; skipped: number }
  summary_report?: {
    headline?: string
    highlights?: string[]
    issues?: Array<{ title?: string; detail?: string; severity?: string; files?: string[] }>
    suggestion?: string
  } | null
  items: Array<{
    external_sample_id: string
    score: number
    passed: boolean
    failures: Array<{ name: string; reason: string; top_issues?: string[]; files?: string[] }>
  }>
}

/** 从指标定义中提取大白话描述：优先 summary → explain.定义 → name */
function metricHint(d: MetricDef): string {
  return d.summary
    ?? d.explain?.rows?.find((r) => r.dt === "定义")?.dd
    ?? d.name
    ?? d.id
}

export default function RunDetail() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const { setCrumbs } = useCrumbs()
  const [run, setRun] = useState<RunData | null>(null)
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const toast = useToast()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const defaultDefs = useScenarioDefaults(run?.scenarioId ?? "courseware")

  useEffect(() => {
    if (!id) return
    api.runDetail(id).then((r) => {
      setRun(r)
      setCrumbs([{ label: "项目看板", to: "/dashboard" }, { label: `#${r.externalRunId}` }])
      // 加载 overview（含失败约束详情）
      api.runOverview(id).then(setOverview).catch(() => {})
    }).catch(() => setRun(null))
  }, [id, setCrumbs])

  if (!run) return <Page><div className="text-muted-foreground">加载运行详情…</div></Page>

  const langfuseUrl = run.langfuseTraceId && run.langfuseHost ? `${run.langfuseHost}/trace/${run.langfuseTraceId}` : null
  const passCount = overview?.summary?.passed ?? run.samples.filter((s) => s.status === "pass" || s.status === "passed").length
  const failCount = overview?.summary?.failed ?? run.samples.filter((s) => s.status === "fail" || s.status === "failed").length
  const metricDefs = extractMetricDefs(run.runConfigSnapshot)
  // 优先用最新场景默认指标定义（id 稳定，name/explain 随场景包更新）；
  // 运行快照里的 metric_definitions 是历史拷贝（旧名/已删指标），仅在默认缺失时回退
  const activeDefs = defaultDefs.length > 0 ? defaultDefs : metricDefs
  const rawMetrics = overview?.metrics_raw ?? run.metrics ?? {}

  function downloadReport(kind: "md" | "json") {
    const m = run!.metrics ?? {}
    const summary = { run: run!.externalRunId, mode: run!.mode, samples: run!.totalSamples, metrics: m, pass: passCount, fail: failCount }
    const mdMetrics = Object.entries(m).map(([k, v]) => `${k}=${fmt3(v)}`).join(" · ")
    const text = kind === "json" ? JSON.stringify(summary, null, 2) : `# 运行 #${run!.externalRunId}\n\n- 样本：${run!.totalSamples}（通过 ${passCount} / 失败 ${failCount}）\n- ${mdMetrics}\n`
    const blob = new Blob([text], { type: kind === "json" ? "application/json" : "text/markdown" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `run-${run!.externalRunId}.${kind}`
    a.click()
    URL.revokeObjectURL(url)
  }

  async function doDelete() {
    if (!id) return
    try {
      await api.deleteRun(id)
      toast.success("已删除")
      setDeleteOpen(false)
      nav(`/project/${run!.projectId}`)
    } catch (e) {
      toast.error("删除失败：" + ((e as Error).message ?? ""))
    }
  }

  // 规则集链接
  const ruleSetId = run.ruleSetVersion?.split(":")[0] ?? run.ruleSetVersion
  const ruleSetLink = run.scenarioId && ruleSetId
    ? `/config/scenarios/${run.scenarioId}/edit?select=rule-sets:${ruleSetId}`
    : null

  // verdict 从 overview 取（与第三方 API 一致）
  const verdict = overview?.verdict
  // reward 类指标 id 从 activeDefs 动态查（unit=score 且有 threshold），去 courseware:reward 直接键
  const rewardDef = activeDefs.find((d) => d.unit === "score" && d.threshold != null)
  const rewardScore = overview?.score ?? (rewardDef ? (rawMetrics[rewardDef.id] ?? 0) : 0)

  // 收集所有失败约束（跨样本）
  const allFailures = overview?.items?.flatMap((item) =>
    item.failures.map((f) => ({ ...f, sample_id: item.external_sample_id }))
  ) ?? []

  return (
    <Page>
      <PageHead
        title={<span className="flex items-center gap-2 font-mono">运行 #{run.externalRunId} <StatusBadge status={run.status} /></span>}
        sub={`${run.mode === "eval_only" ? "仅评估" : run.mode === "pipeline" ? "流水线" : run.mode} 模式 · ${num(run.totalSamples)} 个样本 · ${new Date(run.createdAt).toLocaleString("zh-CN")}`}
        right={
          <div className="flex gap-2">
            {langfuseUrl && (
              <Button asChild variant="outline">
                <a href={langfuseUrl} target="_blank" rel="noreferrer">
                  <ExternalLink className="size-4" /> Langfuse
                </a>
              </Button>
            )}
            <Button variant="outline" onClick={() => downloadReport("md")}>
              <Download className="size-4" /> 下载报告
            </Button>
            {run.canDelete && (
              <Button variant="destructive" onClick={() => setDeleteOpen(true)}>
                <Trash2 className="size-4" /> 删除运行
              </Button>
            )}
          </div>
        }
      />

      {/* 紧凑信息条 */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-md border border-border bg-card px-4 py-3 text-xs">
        {ruleSetLink ? (
          <Link to={ruleSetLink} className="inline-flex items-center gap-1.5 text-primary transition-colors hover:underline">
            <FileText className="size-3.5" />
            <span className="text-muted-foreground">规则集</span>
            <span className="font-medium">{run.ruleSetVersion}</span>
          </Link>
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <FileText className="size-3.5 text-muted-foreground" />
            <span className="text-muted-foreground">规则集</span>
            <span className="font-medium">{run.ruleSetVersion ?? "—"}</span>
          </span>
        )}
        <Sep />
        <span className="inline-flex items-center gap-1.5">
          <span className="text-muted-foreground">评估模式</span>
          <span className="font-medium">{run.mode === "eval_only" ? "仅评估" : run.mode === "pipeline" ? "流水线" : run.mode}</span>
        </span>
        <Sep />
        <span className="inline-flex items-center gap-1.5">
          <span className="text-muted-foreground">样本数</span>
          <span className="font-medium tabular-nums">{num(run.totalSamples)}</span>
        </span>
        <Sep />
        <span className="inline-flex items-center gap-1.5">
          <span className="text-muted-foreground">平均耗时</span>
          <span className="font-medium tabular-nums">{fmtMsRaw(rawMetrics["avg_time_ms"] ?? 0)}</span>
        </span>
        <Sep />
        <span className="inline-flex items-center gap-1.5">
          <span className="text-muted-foreground">运行时间</span>
          <span className="font-medium">{new Date(run.createdAt).toLocaleString("zh-CN")}</span>
        </span>
      </div>

      {/* 场景化指标 */}
      <section className="space-y-2">
        <h3 className="text-sm font-medium text-muted-foreground">场景化指标</h3>
        <DynamicMetricGrid defs={activeDefs} metrics={run.metrics} />
      </section>

      {/* 摘要报告 */}
      <SectionCard>
        <SectionCardHeader>
          <SectionCardTitle>摘要报告</SectionCardTitle>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => downloadReport("md")}>MD</Button>
            <Button size="sm" variant="outline" onClick={() => downloadReport("json")}>JSON</Button>
          </div>
        </SectionCardHeader>
        <SectionCardContent className="space-y-4 text-sm">
          {/* LLM 生成的人话摘要（优先展示，未生成时回退到结构化拼装） */}
          {overview?.summary_report ? (
            <>
              {/* headline */}
              <p className={`text-base font-semibold ${
                (overview.summary_report.headline ?? "").includes("良好") || (overview.summary_report.headline ?? "").includes("合格")
                  ? "text-emerald-400"
                  : "text-red-400"
              }`}>
                {overview.summary_report.headline ?? `综合评分 ${fmt3(rewardScore)}`}
              </p>

              {/* 亮点 */}
              {overview.summary_report.highlights && overview.summary_report.highlights.length > 0 && (
                <div className="space-y-1">
                  {overview.summary_report.highlights.map((h, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <span className="mt-0.5 text-emerald-400">✓</span>
                      <span className="text-muted-foreground">{h}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* 问题 */}
              {overview.summary_report.issues && overview.summary_report.issues.length > 0 && (
                <div className="space-y-2 border-t border-border pt-3">
                  <p className="text-xs font-semibold text-muted-foreground">发现的问题</p>
                  {overview.summary_report.issues.map((issue, i) => (
                    <div key={i} className={`rounded-md border p-2.5 ${
                      issue.severity === "high" ? "border-red-500/20 bg-red-500/5" : "border-yellow-500/20 bg-yellow-500/5"
                    }`}>
                      <div className="flex items-center gap-2 text-xs font-medium">
                        <span className={`size-1.5 rounded-full ${issue.severity === "high" ? "bg-red-400" : "bg-yellow-400"}`} />
                        <span className={issue.severity === "high" ? "text-red-400" : "text-yellow-400"}>{issue.title}</span>
                      </div>
                      {issue.detail && <p className="mt-1 text-xs text-muted-foreground">{issue.detail}</p>}
                      {issue.files && issue.files.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {issue.files.map((file, j) => (
                            <span key={j} className="rounded border border-border bg-card px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                              {file}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* 改进建议 */}
              {overview.summary_report.suggestion && (
                <div className="border-t border-border pt-3">
                  <div className="flex items-start gap-2 text-xs">
                    <span className="mt-0.5 text-primary">💡</span>
                    <span className="text-muted-foreground">{overview.summary_report.suggestion}</span>
                  </div>
                </div>
              )}
            </>
          ) : (
            /* 回退：无 summary_report 时用结构化数据拼装 */
            <>
              <div>
                <p className={`text-base font-semibold ${
                  verdict === "pass" ? "text-emerald-400" : "text-red-400"
                }`}>
                  {verdict === "pass"
                    ? `综合评分 ${fmt3(rewardScore)}，质量良好`
                    : rewardScore < 0.5
                      ? "评估未通过，存在严重问题"
                      : `综合评分 ${fmt3(rewardScore)}，存在需改进的问题`
                }
                </p>
                <p className="mt-1 text-muted-foreground">
                  {"共评估 " + num(run.totalSamples) + " 个样本"}
                  {passCount > 0 && <span>，<span className="text-emerald-400">{passCount} 个通过</span></span>}
                  {failCount > 0 && <span>，<span className="text-red-400">{failCount} 个未通过</span></span>}
                  {"。"}
                </p>
              </div>

              {/* 评估详情：指标达标对比（描述来自 summary → explain.定义 → name） */}
              <div className="space-y-1.5 border-t border-border pt-3">
                <p className="text-xs font-semibold text-muted-foreground">评估详情</p>
                {activeDefs
                  .filter((d) => d.threshold != null && rawMetrics[d.id] != null)
                  .map((d) => {
                    const val = rawMetrics[d.id]!
                    const thr = d.threshold as number
                    const ok = val >= thr
                    return (
                      <div key={d.id} className="flex items-center justify-between py-0.5 text-xs">
                        <span className="flex items-center gap-2">
                          <span className={`size-1.5 rounded-full ${ok ? "bg-emerald-400" : "bg-red-400"}`} />
                          <span className="text-muted-foreground">{metricHint(d)}</span>
                        </span>
                        <span className="flex items-center gap-1.5">
                          <span className={`font-mono font-medium ${ok ? "text-emerald-400" : "text-red-400"}`}>{fmt3(val)}</span>
                          <span className="text-muted-foreground/60">达标线 {fmt3(thr)}</span>
                        </span>
                      </div>
                    )
                  })}
              </div>

              {/* 发现的问题：来自 overview API failures */}
              {allFailures.length > 0 && (
                <div className="space-y-2 border-t border-border pt-3">
                  <p className="text-xs font-semibold text-muted-foreground">发现的问题</p>
                  {allFailures.slice(0, 10).map((f, i) => (
                    <div key={i} className="rounded-md border border-red-500/20 bg-red-500/5 p-2.5">
                      <div className="flex items-center gap-2 text-xs font-medium text-red-400">
                        <span className="size-1.5 rounded-full bg-red-400" />
                        {f.name}
                      </div>
                      {f.reason && <p className="mt-1 text-xs text-muted-foreground">{f.reason}</p>}
                      {f.top_issues && f.top_issues.length > 0 && (
                        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                          {f.top_issues.map((issue, j) => <li key={j}>{issue}</li>)}
                        </ul>
                      )}
                      {f.files && f.files.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {f.files.map((file, j) => (
                            <span key={j} className="rounded border border-border bg-card px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                              {file}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {/* 查看详细评估结果 */}
          <div className="border-t border-border pt-3">
            <div className="flex flex-wrap gap-2">
              {run.samples.slice(0, 5).map((s) => (
                <Link
                  key={s.id}
                  to={`/run/${id}/sample/${s.id}`}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-2 text-xs transition-colors hover:border-primary/40 hover:bg-primary/5"
                >
                  <FileText className="size-3.5 text-muted-foreground" />
                  <span>查看详细评估</span>
                  <ChevronRight className="size-3 text-muted-foreground" />
                </Link>
              ))}
              {run.samples.length > 5 && (
                <Link
                  to={`/run/${id}/sample/${run.samples[5].id}`}
                  className="inline-flex items-center gap-1 px-2 py-2 text-xs text-primary hover:underline"
                >
                  查看全部 {num(run.samples.length)} 个 →
                </Link>
              )}
            </div>
          </div>
        </SectionCardContent>
      </SectionCard>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除运行</DialogTitle>
            <DialogDescription>删除后该运行的样本、约束结论与制品将永久清除，无法恢复。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button>
            <Button variant="destructive" onClick={doDelete}>确认删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  )
}

function Sep() {
  return <span className="text-border">·</span>
}
