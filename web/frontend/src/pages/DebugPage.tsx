/**
 * 调试台（/debug）—— 登录即可访问。左右结构：左侧参数+结果，右侧 Console 日志流。
 * 实时输出 request / response / 轮询 / 结果全过程，类似浏览器 DevTools Console。
 * 项目归属由 API Key 决定（Web 后端验签解析），无需也不接收 project_id。
 */
import { useEffect, useRef, useState } from "react"
import { api, type CatalogEntry, type ScenarioCatalog } from "../api/client"
import { DynamicMetricGrid } from "@/components/DynamicMetricGrid"
import { useScenarioDefaults } from "@/hooks/useScenarioDefaults"
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
import { useCrumbs } from "../context/navigation"
import { FilePicker } from "../components/FilePicker"
import { useToast } from "../hooks/useToast"
import { StatusBadge } from "../components/shared"
import { CopyIcon, ExternalLink, FileJson, HelpCircle, Terminal, Trash2 } from "lucide-react"
import type { DebugJobStatus } from "../types"

const POLL_INTERVAL = 30000

/** 由场景包目录项推导 package_ref（scenario/asset_id:label，优先 production 标签）。 */
function packageRefOf(scenario: string, pkg: CatalogEntry): string {
  const label = pkg.labels.includes("production") ? "production" : (pkg.labels[0] ?? pkg.version)
  return `${scenario}/${pkg.asset_id}:${label}`
}

/** 参数默认值（用户可在编辑框内直接修改）。 */
const DEFAULTS = {
  scenario: "courseware",
  taskId: "",
  taskTitle: "",
  apiKey: "",
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

function ParamLabel({ name, required, help }: { name: string; required?: boolean; help: string }) {
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
        <TooltipContent side="top" className="max-w-[260px] whitespace-pre-line">
          {help}
        </TooltipContent>
      </Tooltip>
    </div>
  )
}

export default function DebugPage() {
  const { setCrumbs } = useCrumbs()
  const toast = useToast()

  const [scenario, setScenario] = useState(DEFAULTS.scenario)
  const [scenarios, setScenarios] = useState<Array<{ id: string; name: string }>>([])
  const [catalog, setCatalog] = useState<ScenarioCatalog | null>(null)
  const [ruleSet, setRuleSet] = useState("coursework-quality")
  const [packageAssetId, setPackageAssetId] = useState<string>("")
  const [taskId, setTaskId] = useState(DEFAULTS.taskId)
  const [taskTitle, setTaskTitle] = useState(DEFAULTS.taskTitle)
  const [apiKey, setApiKey] = useState(DEFAULTS.apiKey)
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [job, setJob] = useState<DebugJobStatus | null>(null)
  const [activeJob, setActiveJob] = useState<{
    jobId: string
    apiKey: string
  } | null>(null)
  const [logs, setLogs] = useState<ConsoleEntry[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const logIdRef = useRef(0)
  const consoleRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    setCrumbs([{ label: "调试台" }])
    return () => setCrumbs([])
  }, [setCrumbs])

  // 挂载时拉取场景列表
  useEffect(() => {
    api
      .scenarios()
      .then((items) => setScenarios(items.map((s) => ({ id: s.id, name: s.name }))))
      .catch(() => {
        /* 拉取失败不阻塞：选择器回退到当前 scenario */
      })
  }, [])

  // scenario 变化时拉取场景 catalog（rule_sets + packages 同源），重置 rule_set / package 默认
  useEffect(() => {
    let stopped = false
    api
      .scenarioCatalog(scenario)
      .then((cat) => {
        if (stopped || !cat) return
        setCatalog(cat)
        const rs = cat.rule_sets.map((r) => r.asset_id)
        if (!rs.includes(ruleSet)) {
          setRuleSet(rs.includes("coursework-quality") ? "coursework-quality" : (rs[0] ?? ""))
        }
        const prod = cat.packages.find((p) => p.labels.includes("production"))
        setPackageAssetId(prod?.asset_id ?? cat.packages[0]?.asset_id ?? "")
      })
      .catch(() => {
        /* catalog 拉取失败：选择器回退到当前值 */
      })
    return () => {
      stopped = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario])

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
      const { jobId, apiKey: ak } = activeJob
      pushLog("req", `GET /v1/jobs/${jobId.slice(0, 8)}…`, {
        url: `/api/v1/debug/jobs/${jobId}`,
        method: "GET",
        query: ak.trim() ? { api_key: ak.trim() } : {},
      })
      try {
        const j = await api.getDebugJob(jobId, ak.trim() || undefined)
        if (stopped) return
        pushLog("resp", j.status, j)
        setJob(j)
        if (j.status === "completed") {
          const m = (j.metrics as { metrics?: Record<string, number> } | null)?.metrics
          const rewardKey = m ? Object.keys(m).find((k) => k.endsWith(":reward")) : undefined
          pushLog("info", `评估完成${rewardKey && m ? `  ${rewardKey}=${m[rewardKey]}` : ""}`, j)
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
  }, [activeJob])

  // 由所选场景包推导 package_ref（scenario/asset_id:label）
  const selectedPackage = catalog?.packages.find((p) => p.asset_id === packageAssetId)
  const packageRef = selectedPackage ? packageRefOf(scenario, selectedPackage) : undefined
  // 由所选 rule_set 的 format 门控扩展名推导可上传类型（code→.py / courseware→.html,.md）
  const selectedRuleSet = catalog?.rule_sets.find((r) => r.asset_id === ruleSet)
  const accept = selectedRuleSet?.accept?.length
    ? selectedRuleSet.accept.map((e) => "." + e).join(",")
    : ".html,.htm,.md,.markdown,.zip,.py"

  async function submit() {
    if (!file) return
    if (!packageRef) {
      toast.error("该场景无可用的场景包（package_ref），无法提交")
      return
    }
    setSubmitting(true)
    pushLog("req", "POST /v1/jobs", {
      url: `/api/v1/debug/jobs`,
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      query: {
        filename: file.name,
        rule_set_id: ruleSet,
        package_ref: packageRef,
        ...(taskId.trim() ? { task_id: taskId.trim() } : {}),
        ...(taskTitle.trim() ? { task_title: taskTitle.trim() } : {}),
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      },
      body: `${file.name} (${(file.size / 1024).toFixed(1)} KB)`,
    })
    try {
      const res = await api.submitDebugJob(file, ruleSet, {
        packageRef,
        taskId: taskId.trim() || undefined,
        taskTitle: taskTitle.trim() || undefined,
        apiKey: apiKey.trim() || undefined,
      })
      pushLog("resp", "202 Accepted", res.debug ?? res)
      setJob({ job_id: res.job_id, status: res.status })
      setActiveJob({ jobId: res.job_id, apiKey })
      toast.success(`已提交，job_id=${res.job_id.slice(0, 8)}…`)
    } catch (e) {
      const msg = e as {
        response?: {
          data?: { details?: { upstreamBody?: string }; error?: string; message?: string }
        }
      }
      // 后端统一错误体字段为 error（errorHandler），旧代码误读 message 导致恒回退到"提交失败"
      const detail =
        msg.response?.data?.details?.upstreamBody?.slice(0, 300) ||
        msg.response?.data?.error ||
        msg.response?.data?.message ||
        "提交失败"
      pushLog("error", "提交失败", detail)
      toast.error(detail.slice(0, 120))
    } finally {
      setSubmitting(false)
    }
  }

  // executor（阶段1场景化）直出 courseware:* 指标键，无需旧→新映射
  const metrics = (job?.metrics as { metrics?: Record<string, number> } | null)?.metrics
  const defaultDefs = useScenarioDefaults(scenario)

  return (
    <TooltipProvider>
      <div className="flex h-[calc(100vh-3.5rem)]">
        {/* 左侧：参数 + 结果 */}
        <div className="w-[30rem] shrink-0 space-y-4 overflow-y-auto border-r p-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">调试台</h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              向 Web 后端提交评估，由 executor 异步执行，实时查看请求 / 响应 / 结果。
            </p>
          </div>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">参数配置</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <ParamLabel
                  name="scenario"
                  help="场景（决定可用的规则集与场景包）。切换后自动拉取该场景 catalog。"
                />
                <Select value={scenario} onValueChange={setScenario}>
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(scenarios.length ? scenarios : [{ id: scenario, name: scenario }]).map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        <span className="flex items-center gap-1.5">
                          <span>{s.name || s.id}</span>
                          {s.name && s.name !== s.id && (
                            <span className="font-mono text-[10px] text-muted-foreground">{s.id}</span>
                          )}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <ParamLabel
                  name="rule_set_id"
                  help="规则集来自所选场景的 catalog（与场景包同源）。"
                />
                <Select value={ruleSet} onValueChange={setRuleSet}>
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(catalog?.rule_sets.length
                      ? catalog.rule_sets
                      : [{ asset_id: ruleSet, name: ruleSet, version: "", labels: [], description: null }]
                    ).map((r) => (
                      <SelectItem key={r.asset_id} value={r.asset_id}>
                        <span className="flex items-center gap-1.5">
                          <span>{r.name || r.asset_id}</span>
                          {r.name && r.name !== r.asset_id && (
                            <span className="font-mono text-[10px] text-muted-foreground">
                              {r.asset_id}
                            </span>
                          )}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <ParamLabel
                  name="package_ref"
                  required
                  help={`场景包引用（scenario/package:label），executor 据此解析规则集文件；不再对 courseware 自动补全。当前：${packageRef ?? "（该场景无可用包）"}`}
                />
                <Select value={packageAssetId} onValueChange={setPackageAssetId}>
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue placeholder="无可用场景包" />
                  </SelectTrigger>
                  <SelectContent>
                    {(catalog?.packages ?? []).map((p) => (
                      <SelectItem key={p.asset_id} value={p.asset_id}>
                        <span className="flex items-center gap-1.5">
                          <span>{p.name || p.asset_id}</span>
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {scenario}/{p.asset_id}:
                            {p.labels.includes("production") ? "production" : (p.labels[0] ?? p.version)}
                          </span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <ParamLabel
                  name="task_id"
                  help={
                    "自定义任务标识，决定 run 内 sample_id；留空则单页恒为 contents。\n\n示例：lesson-3"
                  }
                />
                <Input
                  value={taskId}
                  onChange={(e) => setTaskId(e.target.value)}
                  className="h-9 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <ParamLabel
                  name="task_title"
                  help={"任务展示标题；留空则用 job_id 兜底。\n\n示例：分数入门"}
                />
                <Input
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                  className="h-9 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <ParamLabel
                  name="api_key"
                  required
                  help={
                    "Bearer 鉴权 Key，决定结果归属的项目（Web 后端据此验签解析 project_id）。\n\n获取方法：项目详情页 → API Key 管理，创建后复制 eval- 开头的明文（仅创建时可见一次）。"
                  }
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
                  accept={accept}
                  hint={selectedRuleSet?.accept?.map((e) => "." + e).join(" / ") ?? "按规则集格式门控"}
                />
              </div>

              <Button disabled={!file || submitting || !packageRef} onClick={submit} size="sm" className="w-full">
                {submitting ? "提交中…" : "提交评估"}
              </Button>
            </CardContent>
          </Card>

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
                  <DynamicMetricGrid defs={defaultDefs} metrics={metrics} />
                )}
                {job.status === "completed" && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={async () => {
                      if (!job) return
                      pushLog("req", `GET /debug/jobs/${job.job_id.slice(0, 8)}/overview`, {
                        url: `/api/v1/debug/jobs/${job.job_id}/overview`,
                        method: "GET",
                      })
                      try {
                        const ov = await api.getDebugOverview(job.job_id, apiKey.trim() || undefined)
                        pushLog("resp", "200", ov)
                        pushLog("info", `Overview: verdict=${(ov as { verdict?: string }).verdict ?? "—"} score=${(ov as { score?: number }).score ?? "—"}`, ov)
                      } catch (e) {
                        pushLog("error", "Overview 获取失败", String(e))
                      }
                    }}
                  >
                    <FileJson className="size-3.5" /> 获取 Overview 速览
                  </Button>
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
          <div
            ref={consoleRef}
            className="flex-1 space-y-0.5 overflow-y-auto p-3 font-mono text-xs"
          >
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
                      <span className="w-16 shrink-0 select-none text-muted-foreground/70">
                        {log.ts}
                      </span>
                      <span className="flex-1 truncate">{log.label}</span>
                      {log.data != null && (
                        <span className="shrink-0 text-muted-foreground/50 group-open:hidden">
                          ▸
                        </span>
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
