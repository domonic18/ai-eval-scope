import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api } from "../api/client"
import { fmt3, fmtMsRaw, num } from "../lib/format"
import { METRIC_LABEL, THRESHOLDS } from "../lib/eval"
import type { MetricKey } from "../lib/eval"
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
import { useCrumbs } from "../components/AppShell"
import { useToast } from "../components/toast"
import { DataTable, PageHead, StatusBadge, type Column } from "../components/shared"
import { Download, ExternalLink, Trash2 } from "lucide-react"

interface SampleRow {
  id: string
  externalSampleId: string
  status: string
  reward: number
  sFormat: number
  sCommon: number
  sSoft: number
  sPref: number
}
interface RunData {
  id: string
  externalRunId: string
  projectId: string
  canDelete: boolean
  mode: string
  status: string
  totalSamples: number
  dr: number
  cpr: number
  avgReward: number
  avgSoft: number
  avgPref: number
  condR: number
  avgTimeMs: number
  ruleSetVersion: string | null
  langfuseTraceId: string | null
  langfuseHost: string | null
  createdAt: string
  samples: SampleRow[]
}
type StageFilter = "format" | "commonsense" | "soft" | "pref" | null

function stageFail(s: SampleRow, stage: NonNullable<StageFilter>): boolean {
  switch (stage) {
    case "format":
      return s.sFormat < 1
    case "commonsense":
      return s.sCommon <= 0
    case "soft":
      return s.sSoft < 0.6
    case "pref":
      return s.sPref < 0.6
  }
}
function worstStage(s: SampleRow): string | null {
  if (s.sFormat < 1) return "format"
  if (s.sCommon <= 0) return "commonsense"
  if (s.sSoft < 0.6) return "soft"
  if (s.sPref < 0.6) return "pref"
  return null
}
function tierCls(chip: "hard" | "soft" | "pref" | null): string {
  if (chip === "hard") return "border-red-500/40 text-red-400"
  if (chip === "soft") return "border-yellow-500/40 text-yellow-400"
  if (chip === "pref") return "border-sky-500/40 text-sky-400"
  return "border-border text-muted-foreground"
}

function FailBar({ name, count, max, color, active, onClick }: { name: string; count: number; max: number; color: string; active?: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className={`block w-full rounded-md px-2 py-1.5 text-left transition-colors hover:bg-accent/50 ${active ? "bg-accent/60" : ""}`}>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span>{name}</span>
        <span className="font-mono tabular-nums text-muted-foreground">{count}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full" style={{ width: `${(count / max) * 100}%`, background: color }} />
      </div>
    </button>
  )
}

export default function RunDetail() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const { setCrumbs } = useCrumbs()
  const [run, setRun] = useState<RunData | null>(null)
  const [stageFilter, setStageFilter] = useState<StageFilter>(null)
  const [seg, setSeg] = useState<"all" | "fail" | "skip">("all")
  const toast = useToast()
  const [deleteOpen, setDeleteOpen] = useState(false)

  useEffect(() => {
    if (!id) return
    api.runDetail(id).then((r) => {
      setRun(r)
      setCrumbs([{ label: "项目看板", to: "/dashboard" }, { label: `#${r.externalRunId}` }])
    }).catch(() => setRun(null))
  }, [id, setCrumbs])

  const failCounts = useMemo(() => {
    if (!run) return null
    const s = run.samples
    return {
      format: s.filter((x) => stageFail(x, "format")).length,
      commonsense: s.filter((x) => stageFail(x, "commonsense")).length,
      soft: s.filter((x) => stageFail(x, "soft")).length,
      pref: s.filter((x) => stageFail(x, "pref")).length,
    }
  }, [run])
  const failMax = failCounts ? Math.max(failCounts.format, failCounts.commonsense, failCounts.soft, failCounts.pref, 1) : 1

  const filteredSamples = useMemo(() => {
    if (!run) return []
    return run.samples.filter((s) => {
      if (seg === "fail" && s.status !== "fail" && s.status !== "failed") return false
      if (seg === "skip" && s.status !== "skip" && s.status !== "skipped") return false
      if (stageFilter && !stageFail(s, stageFilter)) return false
      return true
    })
  }, [run, seg, stageFilter])

  if (!run) return <div className="p-8 text-muted-foreground">加载运行详情…</div>

  const langfuseUrl = run.langfuseTraceId && run.langfuseHost ? `${run.langfuseHost}/trace/${run.langfuseTraceId}` : null
  const passCount = run.samples.filter((s) => s.status === "pass" || s.status === "passed").length
  const failCount = run.samples.filter((s) => s.status === "fail" || s.status === "failed").length

  function downloadReport(kind: "md" | "json") {
    const summary = {
      run: run!.externalRunId,
      mode: run!.mode,
      samples: run!.totalSamples,
      metrics: { DR: run!.dr, CPR: run!.cpr, Reward: run!.avgReward, CondR: run!.condR },
      pass: passCount,
      fail: failCount,
    }
    const text = kind === "json" ? JSON.stringify(summary, null, 2) : `# 运行 #${run!.externalRunId}\n\n- 样本：${run!.totalSamples}（通过 ${passCount} / 失败 ${failCount}）\n- DR=${fmt3(run!.dr)} · CPR=${fmt3(run!.cpr)} · Reward=${fmt3(run!.avgReward)} · CondR=${fmt3(run!.condR)}\n`
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

  const metricRows: { k: MetricKey; val: number; thr: number }[] = [
    { k: "DR", val: run.dr, thr: THRESHOLDS.DR },
    { k: "CPR", val: run.cpr, thr: THRESHOLDS.CPR },
    { k: "Soft", val: run.avgSoft, thr: THRESHOLDS.Soft },
    { k: "Pref", val: run.avgPref, thr: THRESHOLDS.Pref },
    { k: "Reward", val: run.avgReward, thr: THRESHOLDS.Reward },
  ]
  const meta = [
    { lab: "规则集", val: run.ruleSetVersion ?? "—" },
    { lab: "评估模式", val: run.mode },
    { lab: "样本数", val: num(run.totalSamples) },
    { lab: "平均耗时/样本", val: fmtMsRaw(run.avgTimeMs) },
    { lab: "创建时间", val: new Date(run.createdAt).toLocaleString("zh-CN") },
  ]

  return (
    <div className="space-y-6 p-6">
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

      {/* meta */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {meta.map((m) => (
          <Card key={m.lab}>
            <CardContent className="pt-5">
              <div className="text-xs text-muted-foreground">{m.lab}</div>
              <div className="mt-1 font-mono text-sm">{m.val}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* metric cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {metricRows.map((m) => {
          const ok = m.val >= m.thr
          return (
            <Card key={m.k}>
              <CardContent className="pt-5">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">{METRIC_LABEL[m.k]}</span>
                  <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] ${ok ? "border-emerald-500/40 text-emerald-400" : "border-yellow-500/40 text-yellow-400"}`}>
                    {ok ? "达标" : "未达"}
                  </span>
                </div>
                <div className={`mt-1 text-2xl font-semibold tabular-nums ${ok ? "" : "text-yellow-400"}`}>{fmt3(m.val)}</div>
                <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
                  <div className={`h-full rounded-full ${ok ? "bg-emerald-500" : "bg-yellow-500"}`} style={{ width: `${Math.min(100, m.val * 100)}%` }} />
                </div>
                <div className="mt-1 text-[11px] text-muted-foreground">阈值 ≥ {m.thr}</div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 失败分布 */}
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">失败分布</CardTitle>
            <span className="text-xs text-muted-foreground">点击下钻样本</span>
          </CardHeader>
          <CardContent className="space-y-1">
            {failCounts && failCounts.format + failCounts.commonsense + failCounts.soft + failCounts.pref === 0 ? (
              <div className="py-6 text-center text-sm text-muted-foreground">无失败/偏低项</div>
            ) : (
              <>
                <FailBar name="format 格式门禁" count={failCounts?.format ?? 0} max={failMax} color="var(--destructive)" active={stageFilter === "format"} onClick={() => setStageFilter(stageFilter === "format" ? null : "format")} />
                <FailBar name="commonsense 常识" count={failCounts?.commonsense ?? 0} max={failMax} color="var(--destructive)" active={stageFilter === "commonsense"} onClick={() => setStageFilter(stageFilter === "commonsense" ? null : "commonsense")} />
                <FailBar name="soft 软约束偏低" count={failCounts?.soft ?? 0} max={failMax} color="var(--chart-3)" active={stageFilter === "soft"} onClick={() => setStageFilter(stageFilter === "soft" ? null : "soft")} />
                <FailBar name="preference 偏好偏低" count={failCounts?.pref ?? 0} max={failMax} color="var(--chart-4)" active={stageFilter === "pref"} onClick={() => setStageFilter(stageFilter === "pref" ? null : "pref")} />
              </>
            )}
          </CardContent>
        </Card>

        {/* 报告摘要 */}
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">报告摘要</CardTitle>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => downloadReport("md")}>MD</Button>
              <Button size="sm" variant="outline" onClick={() => downloadReport("json")}>JSON</Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p>
              本次 {num(run.totalSamples)} 个样本，<span className="font-medium text-emerald-400">{passCount} 通过</span> / <span className="font-medium text-red-400">{failCount} 失败</span>。
              DR {run.dr >= THRESHOLDS.DR ? "达标" : "未达"}（{fmt3(run.dr)}）、CPR {run.cpr >= THRESHOLDS.CPR ? "达标" : "未达"}（{fmt3(run.cpr)}），Reward <span className={run.avgReward >= THRESHOLDS.Reward ? "text-emerald-400" : "text-red-400"}>{run.avgReward >= THRESHOLDS.Reward ? "达标" : `偏低（${fmt3(run.avgReward)}）`}</span>。
            </p>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              {!!failCounts?.format && <li>{failCounts.format} 个样本未通过格式门禁。</li>}
              {!!failCounts?.commonsense && <li>{failCounts.commonsense} 个样本存在常识性错误。</li>}
              {!!failCounts?.soft && <li>{failCounts.soft} 个样本软约束偏低（&lt; 0.6）。</li>}
              {!!failCounts?.pref && <li>{failCounts.pref} 个样本偏好偏低（&lt; 0.6）。</li>}
              {(!failCounts || (failCounts.format + failCounts.commonsense + failCounts.soft + failCounts.pref === 0)) && <li>未发现明显短板。</li>}
            </ul>
          </CardContent>
        </Card>
      </div>

      {/* 样本表 */}
      <Card id="samples">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">
            样本 <span className="ml-1 text-muted-foreground">{num(run.samples.length)}</span>
          </CardTitle>
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border p-0.5">
              {([["all", "全部"], ["fail", `失败 ${failCount}`], ["skip", "跳过"]] as const).map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => setSeg(k)}
                  className={`rounded px-2 py-1 text-xs transition-colors ${seg === k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
                >
                  {label}
                </button>
              ))}
            </div>
            {stageFilter && (
              <button onClick={() => setStageFilter(null)} className="inline-flex items-center rounded-md border border-primary/40 px-2 py-0.5 text-xs text-primary">
                筛选：{stageFilter} ✕
              </button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={[
              { key: "externalSampleId", title: "样本 (task_id)", render: (s) => <span className="font-mono text-xs">{s.externalSampleId}</span> },
              { key: "status", title: "状态", render: (s) => <StatusBadge status={s.status} /> },
              { key: "reward", title: METRIC_LABEL.Reward, num: true, render: (s) => <span className={s.reward < 0.5 ? "text-red-400" : "text-emerald-400"}>{fmt3(s.reward)}</span> },
              { key: "sFormat", title: "S_format", num: true, render: (s) => <span className={s.sFormat < 1 ? "text-red-400" : ""}>{fmt3(s.sFormat)}</span> },
              { key: "sCommon", title: "S_common", num: true, render: (s) => <span className={s.sCommon <= 0 ? "text-red-400" : ""}>{fmt3(s.sCommon)}</span> },
              { key: "sSoft", title: "S_soft", num: true, render: (s) => fmt3(s.sSoft) },
              { key: "sPref", title: "S_pref", num: true, render: (s) => fmt3(s.sPref) },
              {
                key: "fail",
                title: "失败约束",
                render: (s) => {
                  const w = worstStage(s)
                  const chip = w === "format" || w === "commonsense" ? "hard" : w === "soft" ? "soft" : w === "pref" ? "pref" : null
                  return w ? (
                    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] ${tierCls(chip)}`}>{w}</span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )
                },
              },
            ] as Column<SampleRow>[]}
            rows={filteredSamples}
            rowKey={(s) => s.id}
            onRowClick={(s) => nav(`/run/${id}/sample/${s.id}`)}
            empty="无匹配样本"
          />
        </CardContent>
      </Card>

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
    </div>
  )
}
