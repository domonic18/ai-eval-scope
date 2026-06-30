/**
 * 调试台（/debug）—— owner 专属（shadcn/Tailwind 重写）。
 * 上传 HTML/zip + 配规则集/task_id → 经 web backend 代理转发 eval-gateway → 轮询状态/指标。
 */
import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Label } from "@/components/shadcn/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/shadcn/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/shadcn/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/shadcn/table"
import { useCrumbs, useOrg } from "../components/AppShell"
import { FilePicker } from "../components/FilePicker"
import { useToast } from "../components/toast"
import { StatCard } from "../components/shared"
import { ExternalLink } from "lucide-react"
import type { DebugJobStatus } from "../types"

const RULE_SETS = ["coursework-default", "format-only"]
const POLL_INTERVAL = 3000

interface Project {
  id: string
  name: string
  slug: string
}
interface HistoryItem {
  jobId: string
  projectId: string
  projectName: string
  ruleSet: string
  filename: string
  status: string
}

function statusBadge(s: string) {
  const cls =
    s === "completed"
      ? "border-emerald-500/40 text-emerald-400"
      : s === "failed"
        ? "border-red-500/40 text-red-400"
        : s === "running"
          ? "border-sky-500/40 text-sky-400"
          : "border-border text-muted-foreground"
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${cls}`}>
      {s}
    </span>
  )
}

export default function DebugPage() {
  const { activeOrg, memberships } = useOrg()
  const { setCrumbs } = useCrumbs()
  const toast = useToast()

  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState("")
  const [ruleSet, setRuleSet] = useState(RULE_SETS[0])
  const [taskId, setTaskId] = useState("")
  const [taskTitle, setTaskTitle] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [job, setJob] = useState<DebugJobStatus | null>(null)
  const [activeJob, setActiveJob] = useState<{ projectId: string; jobId: string } | null>(null)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const isOwner = memberships.find((m) => m.orgId === activeOrg)?.role === "owner"

  useEffect(() => {
    setCrumbs([{ label: "调试台" }])
    return () => setCrumbs([])
  }, [setCrumbs])

  useEffect(() => {
    if (!activeOrg) return
    api
      .dashboard(activeOrg)
      .then((ps: Project[]) => {
        setProjects(ps)
        setProjectId((cur) => cur || ps[0]?.id || "")
      })
      .catch(() => toast.error("加载项目列表失败"))
  }, [activeOrg, toast])

  useEffect(() => {
    if (!activeJob) return
    let stopped = false
    const tick = async () => {
      try {
        const j = await api.getDebugJob(activeJob.projectId, activeJob.jobId)
        if (stopped) return
        setJob(j)
        setHistory((h) => h.map((it) => (it.jobId === j.job_id ? { ...it, status: j.status } : it)))
        if (j.status === "completed" || j.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch {
        /* 单次轮询失败静默 */
      }
    }
    tick()
    pollRef.current = setInterval(tick, POLL_INTERVAL)
    return () => {
      stopped = true
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [activeJob])

  async function submit() {
    if (!projectId || !file) return
    setSubmitting(true)
    try {
      const res = await api.submitDebugJob(projectId, file, ruleSet, {
        taskId: taskId.trim() || undefined,
        taskTitle: taskTitle.trim() || undefined,
      })
      const proj = projects.find((p) => p.id === projectId)
      setJob({ job_id: res.job_id, status: res.status })
      setActiveJob({ projectId, jobId: res.job_id })
      setHistory((h) => [
        {
          jobId: res.job_id,
          projectId,
          projectName: proj?.name ?? projectId,
          ruleSet,
          filename: file.name,
          status: res.status,
        },
        ...h,
      ])
      toast.success(`已提交，job_id=${res.job_id.slice(0, 8)}…`)
    } catch (e) {
      const msg = e as { response?: { data?: { details?: { upstreamBody?: string } }; message?: string } }
      toast.error(msg.response?.data?.details?.upstreamBody?.slice(0, 120) || "提交失败")
    } finally {
      setSubmitting(false)
    }
  }

  const m = job?.metrics?.metrics
  const finished = job?.status === "completed" || job?.status === "failed"

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          调试台
          <span className="ml-2 inline-flex items-center rounded-md border border-yellow-500/40 px-2 py-0.5 text-xs font-medium text-yellow-400">
            owner
          </span>
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          向 eval-gateway 提交评估请求，验证课件（单页 / 单元包）质量。结果落到所选项目。
        </p>
      </div>

      {!isOwner ? (
        <div className="rounded-lg border border-yellow-500/40 bg-yellow-500/5 p-4 text-sm text-yellow-400">
          当前组织你不是 owner，无权使用调试台。
        </div>
      ) : projects.length === 0 ? (
        <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
          当前组织下还没有项目，请先创建项目并签发 API Key。
        </div>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>提交评估</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>目标项目</Label>
                <Select value={projectId} onValueChange={setProjectId}>
                  <SelectTrigger>
                    <SelectValue placeholder="选择项目" />
                  </SelectTrigger>
                  <SelectContent>
                    {projects.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}（{p.slug}）
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  评估结果（run / 制品）落到该项目，用其 API Key 签名转发 gateway。
                </p>
              </div>

              <div className="space-y-2">
                <Label>规则集</Label>
                <Select value={ruleSet} onValueChange={setRuleSet}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RULE_SETS.map((r) => (
                      <SelectItem key={r} value={r}>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>任务 ID（task_id，可选）</Label>
                <Input
                  value={taskId}
                  onChange={(e) => setTaskId(e.target.value)}
                  placeholder="如 lesson-3（留空 → contents）"
                />
                <p className="text-xs text-muted-foreground">
                  决定 run 内 sample_id；不填则单页恒为 contents。
                </p>
              </div>

              <div className="space-y-2">
                <Label>任务标题（task_title，可选）</Label>
                <Input
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                  placeholder="如 分数入门（留空 → job_id）"
                />
              </div>

              <div className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-3 text-xs leading-relaxed text-muted-foreground">
                <strong className="text-foreground">参数说明</strong>
                <div className="mt-1 space-y-0.5">
                  <div>
                    <code>file</code>（必填）：单页 <code>.html/.md</code> 或 <code>.zip</code> 单元包
                  </div>
                  <div>
                    <code>rule_set_id</code>（可选，默认 <code>coursework-default</code>）：
                    <code>coursework-default</code> 完整含 LLM / <code>format-only</code> 仅格式
                  </div>
                  <div>
                    <code>task_id</code> / <code>task_title</code>（可选）：见上
                  </div>
                  <div>
                    <code>scope</code> 自动推断：zip → 单元，单文件 → 单页（不可设）
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <Label>评估内容</Label>
                <FilePicker value={file} onChange={setFile} accept=".html,.htm,.md,.markdown,.zip" hint=".html / .md / .zip" />
                <p className="text-xs text-muted-foreground">
                  zip 课件包 = 单元评估（多文件）；单个 .html/.md = 单页评估
                </p>
              </div>

              <Button disabled={!projectId || !file || submitting} onClick={submit}>
                {submitting ? "提交中…" : "提交评估"}
              </Button>
            </CardContent>
          </Card>

          {job && (
            <Card>
              <CardHeader className="flex-row items-center justify-between space-y-0">
                <CardTitle>任务状态</CardTitle>
                {statusBadge(job.status)}
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="font-mono text-xs text-muted-foreground">job_id: {job.job_id}</div>
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
                  <span>规则集：{job.rule_set_id ?? "—"}</span>
                  <span>范围：{job.scope ?? "—"}</span>
                  <span>提交：{fmtTime(job.created_at)}</span>
                  <span>完成：{fmtTime(job.finished_at)}</span>
                </div>

                {!finished && (
                  <div className="rounded-md border border-sky-500/30 bg-sky-500/5 p-3 text-sm text-sky-400">
                    评估进行中（含 LLM 评判，单元包约 5–7 分钟）…
                  </div>
                )}

                {job.status === "completed" && m && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
                      <StatCard label="DR 交付率" value={fmt3(m.DR)} />
                      <StatCard label="CPR 通过率" value={fmt3(m.CPR)} />
                      <StatCard label="avg_reward" value={fmt3(m.avg_reward)} />
                      <StatCard label="avg_soft" value={fmt3(m.avg_soft)} />
                      <StatCard label="avg_pref" value={fmt3(m.avg_pref)} />
                      <StatCard label="llm_skipped" value={String(m.llm_skipped ?? "—")} />
                    </div>
                    {job.web_run_url && (
                      <Button asChild variant="outline" size="sm">
                        <a href={job.web_run_url} target="_blank" rel="noreferrer">
                          <ExternalLink className="size-4" /> 在 web 平台查看
                        </a>
                      </Button>
                    )}
                  </div>
                )}

                {job.status === "failed" && job.error && (
                  <div className="rounded-md border border-red-500/40 bg-red-500/5 p-3 text-sm">
                    <strong>评估失败：</strong>
                    {job.error.message || "未知错误"}
                    {job.error.traceback && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-muted-foreground">traceback</summary>
                        <pre className="mt-1 whitespace-pre-wrap text-xs">{job.error.traceback}</pre>
                      </details>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {history.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>本次会话提交历史</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>job_id</TableHead>
                        <TableHead>项目</TableHead>
                        <TableHead>文件</TableHead>
                        <TableHead>规则集</TableHead>
                        <TableHead>状态</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {history.map((h) => (
                        <TableRow key={h.jobId}>
                          <TableCell className="font-mono text-xs">{h.jobId.slice(0, 13)}…</TableCell>
                          <TableCell>{h.projectName}</TableCell>
                          <TableCell>{h.filename}</TableCell>
                          <TableCell>{h.ruleSet}</TableCell>
                          <TableCell>{statusBadge(h.status)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

function fmt3(n?: number): string {
  return n == null ? "—" : n.toFixed(3)
}
function fmtTime(iso?: string | null): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleTimeString()
  } catch {
    return iso
  }
}
