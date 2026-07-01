/**
 * 调试台（/debug）—— owner 专属。左右结构：左侧参数+结果，右侧 Console 日志流。
 * 实时输出 request / response / 轮询 / 结果全过程，类似浏览器 DevTools Console。
 */
import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/shadcn/card"
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
import { useCrumbs, useOrg } from "../components/AppShell"
import { FilePicker } from "../components/FilePicker"
import { useToast } from "../components/toast"
import { StatCard, StatusBadge } from "../components/shared"
import { CopyIcon, ExternalLink, HelpCircle, Terminal, Trash2 } from "lucide-react"
import type { DebugJobStatus } from "../types"

const RULE_SETS = ["coursework-default", "format-only"]
const POLL_INTERVAL = 3000

interface Project {
  id: string
  name: string
  slug: string
}

interface ConsoleEntry {
  id: number
  ts: string
  dir: "req" | "resp" | "info" | "error"
  label: string
  data?: unknown
}

const DIR_STYLE: Record<ConsoleEntry["dir"], { icon: string; color: string }> = {
  req: { icon: "→", color: "text-sky-400" },
  resp: { icon: "←", color: "text-emerald-400" },
  info: { icon: "★", color: "text-purple-400" },
  error: { icon: "✗", color: "text-red-400" },
}

function JsonBlock({ data }: { data: unknown }) {
  const text = JSON.stringify(data, null, 2)
  return (
    <div className="relative mt-1.5">
      <Button
        variant="ghost"
        size="icon-xs"
        className="absolute right-1 top-1 size-6"
        onClick={() => navigator.clipboard.writeText(text)}
      >
        <CopyIcon className="size-3" />
      </Button>
      <pre className="overflow-x-auto rounded-md border bg-secondary/40 p-2 pr-8 text-xs leading-relaxed">
        <code>{text}</code>
      </pre>
    </div>
  )
}

function ParamLabel({
  name,
  required,
  help,
}: {
  name: string
  required?: boolean
  help: string
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-xs font-medium">{name}</span>
      {required && <span className="text-red-400">*</span>}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="text-muted-foreground/60 transition-colors hover:text-foreground"
          >
            <HelpCircle className="size-3" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[220px]">
          {help}
        </TooltipContent>
      </Tooltip>
    </div>
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
  const [apiKey, setApiKey] = useState("eval-ed817e3285111214188e52da60b3a38f0bcdc0972a00c387")
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [job, setJob] = useState<DebugJobStatus | null>(null)
  const [activeJob, setActiveJob] = useState<{
    projectId: string
    jobId: string
    apiKey: string
  } | null>(null)
  const [logs, setLogs] = useState<ConsoleEntry[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const logIdRef = useRef(0)
  const consoleRef = useRef<HTMLDivElement>(null)
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

  const pushLog = (dir: ConsoleEntry["dir"], label: string, data?: unknown) => {
    logIdRef.current += 1
    setLogs((prev) => [
      ...prev,
      {
        id: logIdRef.current,
        ts: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
        dir,
        label,
        data,
      },
    ])
  }

  // 自动滚动到底
  useEffect(() => {
    if (autoScroll && consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  // 轮询
  useEffect(() => {
    if (!activeJob) return
    let stopped = false
    const tick = async () => {
      const { projectId: pid, jobId, apiKey: ak } = activeJob
      pushLog("req", `GET /v1/jobs/${jobId.slice(0, 8)}…`, {
        url: `/api/v1/projects/${pid}/debug/jobs/${jobId}`,
        method: "GET",
        query: ak.trim() ? { api_key: ak.trim() } : {},
      })
      try {
        const j = await api.getDebugJob(pid, jobId, ak.trim() || undefined)
        if (stopped) return
        pushLog("resp", j.status, j)
        setJob(j)
        if (j.status === "completed") {
          const m = (j.metrics as { metrics?: { DR?: number } } | null)?.metrics
          pushLog("info", `评估完成  DR=${m?.DR ?? "—"}`, j)
          if (pollRef.current) clearInterval(pollRef.current)
        } else if (j.status === "failed") {
          pushLog("error", "评估失败", j.error)
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch (e) {
        pushLog("error", "查询失败", String(e))
      }
    }
    tick()
    pollRef.current = setInterval(tick, POLL_INTERVAL)
    return () => {
      stopped = true
      if (pollRef.current) clearInterval(pollRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeJob])

  async function submit() {
    if (!projectId || !file) return
    setSubmitting(true)
    pushLog("req", "POST /v1/jobs", {
      url: `/api/v1/projects/${projectId}/debug/jobs`,
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      query: {
        filename: file.name,
        rule_set_id: ruleSet,
        ...(taskId.trim() ? { task_id: taskId.trim() } : {}),
        ...(taskTitle.trim() ? { task_title: taskTitle.trim() } : {}),
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      },
      body: `${file.name} (${(file.size / 1024).toFixed(1)} KB)`,
    })
    try {
      const res = await api.submitDebugJob(projectId, file, ruleSet, {
        taskId: taskId.trim() || undefined,
        taskTitle: taskTitle.trim() || undefined,
        apiKey: apiKey.trim() || undefined,
      })
      pushLog("resp", "202 Accepted", res.debug ?? res)
      setJob({ job_id: res.job_id, status: res.status })
      setActiveJob({ projectId, jobId: res.job_id, apiKey })
      toast.success(`已提交，job_id=${res.job_id.slice(0, 8)}…`)
    } catch (e) {
      const msg = e as {
        response?: { data?: { details?: { upstreamBody?: string }; message?: string } }
      }
      const detail =
        msg.response?.data?.details?.upstreamBody?.slice(0, 300) ||
        msg.response?.data?.message ||
        "提交失败"
      pushLog("error", "提交失败", detail)
      toast.error(detail.slice(0, 120))
    } finally {
      setSubmitting(false)
    }
  }

  const metrics = (job?.metrics as { metrics?: Record<string, number> } | null)?.metrics

  return (
    <TooltipProvider>
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* 左侧：参数 + 结果 */}
      <div className="w-96 shrink-0 space-y-4 overflow-y-auto border-r p-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">调试台</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            向 gateway 提交评估，实时查看请求 / 响应 / 结果。
          </p>
        </div>

        {!isOwner ? (
          <div className="rounded-lg border border-yellow-500/40 bg-yellow-500/5 p-3 text-xs text-yellow-400">
            当前组织你不是 owner，无权使用调试台。
          </div>
        ) : projects.length === 0 ? (
          <div className="rounded-lg border bg-card p-6 text-center text-xs text-muted-foreground">
            当前组织下还没有项目。
          </div>
        ) : (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">参数配置</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <ParamLabel
                  name="project_id"
                  required
                  help="评估结果（run / 样本 / 制品）落到该项目，用其 API Key 鉴权转发 gateway。"
                />
                <Select value={projectId} onValueChange={setProjectId}>
                  <SelectTrigger className="h-9 text-xs">
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
              </div>

              <div className="space-y-1.5">
                <ParamLabel
                  name="rule_set_id"
                  help="coursework-default 完整评估（含 LLM 评判）；format-only 仅格式检查（无 LLM，速度快）。"
                />
                <Select value={ruleSet} onValueChange={setRuleSet}>
                  <SelectTrigger className="h-9 text-xs">
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

              <div className="space-y-1.5">
                <ParamLabel
                  name="task_id"
                  help="自定义任务标识，决定 run 内 sample_id；留空则单页恒为 contents。"
                />
                <Input
                  value={taskId}
                  onChange={(e) => setTaskId(e.target.value)}
                  placeholder="如 lesson-3"
                  className="h-9 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <ParamLabel
                  name="task_title"
                  help="任务展示标题；留空则用 job_id 兜底。"
                />
                <Input
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                  placeholder="如 分数入门"
                  className="h-9 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <ParamLabel
                  name="api_key"
                  help="Bearer 鉴权 Key；留空则用所选项目首个未吊销 Key。"
                />
                <Input
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="eval-…"
                  className="h-9 font-mono text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <ParamLabel
                  name="file"
                  required
                  help=".html / .md = 单页评估；.zip = 单元评估（保留目录结构）。"
                />
                <FilePicker
                  value={file}
                  onChange={setFile}
                  accept=".html,.htm,.md,.markdown,.zip"
                  hint=".html / .md / .zip"
                />
              </div>

              <Button
                disabled={!projectId || !file || submitting}
                onClick={submit}
                size="sm"
                className="w-full"
              >
                {submitting ? "提交中…" : "提交评估"}
              </Button>
            </CardContent>
          </Card>
        )}

        {/* 当前结果 */}
        {job && (
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
              <CardTitle className="text-sm">当前结果</CardTitle>
              <StatusBadge status={job.status} />
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="font-mono text-xs text-muted-foreground">job_id: {job.job_id}</div>
              {job.status === "completed" && metrics && (
                <div className="grid grid-cols-3 gap-2">
                  <StatCard label="DR" value={fmt3(metrics.DR)} />
                  <StatCard label="CPR" value={fmt3(metrics.CPR)} />
                  <StatCard label="Reward" value={fmt3(metrics.avg_reward)} />
                </div>
              )}
              {job.web_run_url && (
                <Button asChild variant="outline" size="sm" className="w-full">
                  <a href={job.web_run_url} target="_blank" rel="noreferrer">
                    <ExternalLink className="size-3.5" /> 在 web 平台查看
                  </a>
                </Button>
              )}
              {job.status === "failed" && job.error && (
                <div className="rounded-md border border-red-500/40 bg-red-500/5 p-2 text-xs text-red-400">
                  {job.error.message || "未知错误"}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {/* 右侧：Console 日志流 */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* 工具栏 */}
        <div className="flex items-center justify-between border-b px-4 py-2">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <Terminal className="size-3.5" /> Console
            <span className="text-muted-foreground/60">({logs.length})</span>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
                className="size-3"
              />
              自动滚动
            </label>
            <Button
              variant="ghost"
              size="icon-xs"
              className="size-6"
              onClick={() => setLogs([])}
              title="清空"
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        </div>
        {/* 日志流 */}
        <div ref={consoleRef} className="flex-1 space-y-0.5 overflow-y-auto p-3 font-mono text-xs">
          {logs.length === 0 ? (
            <div className="italic text-muted-foreground">
              提交评估后，request / response / 轮询 / 结果将在此实时输出…
            </div>
          ) : (
            logs.map((log) => {
              const style = DIR_STYLE[log.dir]
              return (
                <details
                  key={log.id}
                  className="group rounded px-2 py-1 transition-colors hover:bg-muted/30"
                >
                  <summary
                    className={`flex cursor-pointer items-center gap-2 [&::-webkit-details-marker]:hidden ${style.color}`}
                  >
                    <span className="w-3 select-none text-center">{style.icon}</span>
                    <span className="w-16 shrink-0 select-none text-muted-foreground/70">{log.ts}</span>
                    <span className="flex-1 truncate">{log.label}</span>
                    {log.data != null && (
                      <span className="shrink-0 text-muted-foreground/50 group-open:hidden">▸</span>
                    )}
                  </summary>
                  {log.data != null && <JsonBlock data={log.data} />}
                </details>
              )
            })
          )}
        </div>
      </div>
    </div>
    </TooltipProvider>
  )
}

function fmt3(n?: number): string {
  return n == null ? "—" : n.toFixed(3)
}
