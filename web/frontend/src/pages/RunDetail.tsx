import { useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { api } from "../api/client"
import { fmt3, fmtMsRaw, num } from "../lib/format"
import { DynamicMetricGrid } from "../components/DynamicMetricGrid"
import { extractMetricDefs } from "../lib/metricGrid"
import { useScenarioDefaults } from "../hooks/useScenarioDefaults"
import { Button } from "@/components/shadcn/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/shadcn/card"
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

export default function RunDetail() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const { setCrumbs } = useCrumbs()
  const [run, setRun] = useState<RunData | null>(null)
  const toast = useToast()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const defaultDefs = useScenarioDefaults("courseware")

  useEffect(() => {
    if (!id) return
    api.runDetail(id).then((r) => {
      setRun(r)
      setCrumbs([{ label: "项目看板", to: "/dashboard" }, { label: `#${r.externalRunId}` }])
    }).catch(() => setRun(null))
  }, [id, setCrumbs])

  if (!run) return <Page><div className="text-muted-foreground">加载运行详情…</div></Page>

  const langfuseUrl = run.langfuseTraceId && run.langfuseHost ? `${run.langfuseHost}/trace/${run.langfuseTraceId}` : null
  const passCount = run.samples.filter((s) => s.status === "pass" || s.status === "passed").length
  const failCount = run.samples.filter((s) => s.status === "fail" || s.status === "failed").length
  const metricDefs = extractMetricDefs(run.runConfigSnapshot)
  const activeDefs = metricDefs.length > 0 ? metricDefs : defaultDefs

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

  // 规则集链接：跳转场景包编辑器查看规则（需 scenarioId + ruleSetVersion）
  const ruleSetId = run.ruleSetVersion?.split(":")[0] ?? run.ruleSetVersion
  const ruleSetLink = run.scenarioId && ruleSetId
    ? `/config/scenarios/${run.scenarioId}/edit?select=rule-sets:${ruleSetId}`
    : null

  return (
    <Page>
      <PageHead
        title={<span className="flex items-center gap-2 font-mono">运行 #{run.externalRunId} <StatusBadge status={run.status} /></span>}
        sub={`${run.mode} 模式 · ${num(run.totalSamples)} 个样本 · ${new Date(run.createdAt).toLocaleString("zh-CN")}`}
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

      {/* 紧凑信息条（键值对形式，清晰可读） */}
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
          <span className="font-medium tabular-nums">{fmtMsRaw(run.metrics?.["avg_time_ms"] ?? run.metrics?.["courseware:avg_time_ms"] ?? 0)}</span>
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
          {/* 总体评价（人话） */}
          <div className="space-y-2">
            {(() => {
              const reward = run.metrics?.["courseware:reward"] ?? run.metrics?.["reward"] ?? 0
              const dr = run.metrics?.["courseware:document_rate"] ?? run.metrics?.["DR"] ?? 0
              const cpr = run.metrics?.["courseware:constraint_pass_rate"] ?? run.metrics?.["CPR"] ?? 0

              // 总体结论
              let headline: string
              let headlineColor: string
              if (dr < 1) {
                headline = "部分样本格式不合规，无法完成评估"
                headlineColor = "text-red-400"
              } else if (cpr < 0.9) {
                headline = `综合评分 ${fmt3(reward)}，存在明显内容问题需改进`
                headlineColor = "text-red-400"
              } else if (reward < 0.8) {
                headline = `综合评分 ${fmt3(reward)}，基本合格但有提升空间`
                headlineColor = "text-warning"
              } else {
                headline = `综合评分 ${fmt3(reward)}，质量良好`
                headlineColor = "text-emerald-400"
              }

              return (
                <>
                  <p className={`text-base font-semibold ${headlineColor}`}>{headline}</p>
                  <p className="text-muted-foreground">
                    共评估 {num(run.totalSamples)} 个样本，{passCount > 0 && <span className="text-emerald-400">{passCount} 个通过</span>}
                    {passCount > 0 && failCount > 0 && "，"}
                    {failCount > 0 && <span className="text-red-400">{failCount} 个未通过</span>}。
                  </p>
                </>
              )
            })()}
          </div>

          {/* 问题诊断（按指标列出，说人话） */}
          <div className="space-y-1.5 border-t border-border pt-3">
            <p className="text-xs font-semibold text-muted-foreground">评估详情</p>
            {activeDefs
              .filter((d) => d.threshold != null && run.metrics?.[d.id] != null)
              .map((d) => {
                const val = run.metrics![d.id]
                const thr = d.threshold as number
                const ok = val >= thr
                // 用人话解释每个指标的含义
                const hint = d.id.includes("document_rate")
                  ? "所有样本格式是否合规（能正常打开和使用）"
                  : d.id.includes("constraint_pass_rate")
                    ? "内容是否存在事实错误或常识问题"
                    : d.id.includes("reward")
                      ? "综合质量评分（格式 + 内容 + 质量 + 偏好加权）"
                      : d.id.includes("soft")
                        ? "内容质量（教学逻辑、多样性等）"
                        : d.id.includes("pref")
                          ? "用户偏好满足度（风格、深度等）"
                          : d.id.includes("conditional_reward")
                            ? "合格样本的平均质量（排除格式不合格的）"
                            : d.name
                return (
                  <div key={d.id} className="flex items-center justify-between py-0.5 text-xs">
                    <span className="flex items-center gap-2">
                      <span className={`size-1.5 rounded-full ${ok ? "bg-emerald-400" : "bg-red-400"}`} />
                      <span className="text-muted-foreground">{hint}</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className={`font-mono font-medium ${ok ? "text-emerald-400" : "text-red-400"}`}>{fmt3(val)}</span>
                      <span className="text-muted-foreground/60">达标线 {fmt3(thr)}</span>
                    </span>
                  </div>
                )
              })}
          </div>

          {/* 查看详细评估结果 */}
          <div className="border-t border-border pt-3">
            <p className="mb-2 text-xs font-semibold text-muted-foreground">详细评估结果</p>
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
            <DialogDescription>删除后该运行的样本、约束结论与制品将永久清除，无法恢复；走势与看板指标将随之重算。</DialogDescription>
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
