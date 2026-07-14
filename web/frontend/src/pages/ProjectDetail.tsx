import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts"
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/shadcn/chart"
import { api } from "../api/client"
import type {
  ApiKeySafe,
  IssuedApiKey,
  ProjectSample,
  RunSummary,
  SampleTrendPoint,
  TrendPoint,
} from "../types"
import { fmt3, num, timeAgo } from "../lib/format"
import { METRIC_LABEL } from "../lib/eval"
import {
  DynamicMetricGrid,
  COURSEWARE_DEFAULT_METRIC_DEFS,
} from "../components/DynamicMetricGrid"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Label } from "@/components/shadcn/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/shadcn/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/shadcn/tabs"
import { Separator } from "@/components/shadcn/separator"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/shadcn/select"
import { useCrumbs } from "../components/AppShell"
import { useToast } from "../components/toast"
import { DataTable, Page, PageHead, SemPill, StatusBadge, type Column } from "../components/shared"
import { CodeBlock } from "@/components/CodeBlock"
import { Download, Plus, Search, Trash2 } from "lucide-react"

interface Project {
  id: string
  name: string
  slug: string
  description: string | null
  ruleSetVersion?: string | null
  isPublic?: boolean
}
type SetTab = "keys" | "basic" | "retention" | "public" | "danger"

/* ── 趋势图（recharts）── 一组 points({label,values}) + series + thresholds */
function MetricTrendChart({
  points,
  series,
  thresholds = [],
  height = 260,
}: {
  points: { label: string; values: Record<string, number> }[]
  series: { key: string; name: string; color: string }[]
  thresholds?: { label: string; value: number; color: string }[]
  height?: number
}) {
  const data = points.map((p) => ({ label: p.label, ...p.values }))
  const config = Object.fromEntries(
    series.map((s) => [s.key, { label: s.name, color: s.color }]),
  ) satisfies ChartConfig
  return (
    <ChartContainer config={config} className="w-full" style={{ height }}>
      <LineChart data={data} margin={{ left: 4, right: 12, top: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} />
        <YAxis domain={[0, 1]} tickLine={false} axisLine={false} width={32} fontSize={11} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
        {thresholds.map((t, i) => (
          <ReferenceLine
            key={i}
            y={t.value}
            stroke={t.color}
            strokeDasharray="4 4"
            label={{ value: t.label, fontSize: 10, fill: t.color, position: "insideTopRight" }}
          />
        ))}
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            stroke={`var(--color-${s.key})`}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </LineChart>
    </ChartContainer>
  )
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const { setCrumbs } = useCrumbs()

  const [project, setProject] = useState<Project | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runsTotal, setRunsTotal] = useState(0)
  const [trends, setTrends] = useState<TrendPoint[]>([])

  useEffect(() => {
    if (!id) return
    api
      .project(id)
      .then((p) => {
        setProject(p)
        setCrumbs([{ label: "项目看板", to: "/dashboard" }, { label: p.name }])
      })
      .catch(() => {})
    api
      .projectRuns(id, 1, 50)
      .then((r) => {
        setRuns(r.items ?? [])
        setRunsTotal(r.total ?? 0)
      })
      .catch(() => {})
    api.projectTrends(id).then(setTrends).catch(() => setTrends([]))
  }, [id, setCrumbs])

  const trendsAsc = useMemo(
    () => [...trends].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()),
    [trends],
  )
  const latest = trendsAsc[trendsAsc.length - 1]

  const trendPoints = trendsAsc.map((t) => ({
    label: new Date(t.created_at).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" }),
    values: { DR: t.DR, CPR: t.CPR, Reward: t.Reward, Soft: t.Soft, Pref: t.Pref },
  }))
  // 趋势线配色对齐原型 project-detail.html 图例：DR 绿 / CPR 信号青 / Reward 电蓝
  const trendSeries = [
    { key: "DR", name: "交付率(DR)", color: "var(--chart-5)" },
    { key: "CPR", name: "约束通过率(CPR)", color: "var(--chart-2)" },
    { key: "Reward", name: "综合评分(Reward)", color: "var(--chart-1)" },
    { key: "Soft", name: "内容质量分(Soft)", color: "var(--chart-3)" },
    { key: "Pref", name: "用户偏好分(Pref)", color: "var(--chart-4)" },
  ]

  return (
    <Page>
      <PageHead
        title={
          <span className="flex items-center gap-2">
            {project ? project.name : "项目"}
            {project && (
              <SemPill tone="success" dot>
                健康
              </SemPill>
            )}
          </span>
        }
        sub={
          project && (
            <>
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{project.slug}</code> · {num(runsTotal)} 次运行
              {project.ruleSetVersion ? ` · 规则集 ${project.ruleSetVersion}` : ""}
            </>
          )
        }
        right={
          <Button variant="outline">
            <Download className="size-4" /> 导出
          </Button>
        }
      />

      <Tabs defaultValue="overview">
        <TabsList variant="line">
          <TabsTrigger value="overview">概览</TabsTrigger>
          <TabsTrigger value="runs">
            运行 <span className="ml-1 text-muted-foreground">{num(runsTotal)}</span>
          </TabsTrigger>
          <TabsTrigger value="samples">样本</TabsTrigger>
          <TabsTrigger value="settings">设置 & API Key</TabsTrigger>
        </TabsList>
        <Separator className="mb-4" />

        <TabsContent value="overview" className="space-y-4">
          {/* Phase 5：场景化动态指标（COURSEWARE 默认定义 + 最新运行 metrics）*/}
          <DynamicMetricGrid
            defs={COURSEWARE_DEFAULT_METRIC_DEFS}
            metrics={latest?.metrics ?? undefined}
          />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">指标趋势</CardTitle>
            </CardHeader>
            <CardContent>
              {trendsAsc.length > 0 ? (
                <MetricTrendChart points={trendPoints} series={trendSeries} thresholds={[{ label: "综合评分达标 0.8", value: 0.8, color: "var(--chart-1)" }]} />
              ) : (
                <div className="py-8 text-center text-sm text-muted-foreground">
                  完成首次评估运行后，将在此展示 DR / CPR / Reward 趋势。
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">最近运行</CardTitle>
              <button className="text-xs text-primary hover:underline" onClick={() => {}}>
                查看全部 →
              </button>
            </CardHeader>
            <CardContent>
              <DataTable columns={runColumns()} rows={runs.slice(0, 6)} rowKey={(r) => r.id} onRowClick={(r) => nav(`/run/${r.id}`)} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="runs">
          <RunsTab runs={runs} total={runsTotal} onOpen={(r) => nav(`/run/${r.id}`)} />
        </TabsContent>

        <TabsContent value="samples">{id && <SamplesTab projectId={id} />}</TabsContent>

        <TabsContent value="settings">
          {project && (
            <SettingsTab
              projectId={project.id}
              slug={project.slug}
              name={project.name}
              description={project.description}
              isPublic={!!project.isPublic}
              onPublicChanged={(v) => setProject({ ...project, isPublic: v })}
              onArchived={() => nav("/dashboard")}
            />
          )}
        </TabsContent>
      </Tabs>
    </Page>
  )
}

function runColumns(): Column<RunSummary>[] {
  return [
    { key: "externalRunId", title: "运行", render: (r) => <span className="font-mono text-xs">#{r.externalRunId}</span> },
    { key: "mode", title: "模式", render: (r) => <span className="text-xs text-muted-foreground">{r.mode}</span> },
    { key: "status", title: "状态", render: (r) => <StatusBadge status={r.status} /> },
    {
      key: "samples",
      title: "评估内容",
      render: (r) => {
        const ids = (r.samples ?? []).map((s) => s.externalSampleId)
        if (!ids.length) return <span className="text-muted-foreground">—</span>
        if (ids.length === 1) return <span className="font-mono text-xs">{ids[0]}</span>
        return (
          <span className="font-mono text-xs">
            {ids[0]} <span className="text-muted-foreground">+{ids.length - 1}</span>
          </span>
        )
      },
    },
    { key: "dr", title: METRIC_LABEL.DR, num: true, render: (r) => fmt3(r.dr) },
    { key: "cpr", title: METRIC_LABEL.CPR, num: true, render: (r) => fmt3(r.cpr) },
    { key: "avgReward", title: METRIC_LABEL.Reward, num: true, render: (r) => fmt3(r.avgReward) },
    { key: "createdAt", title: "时间", render: (r) => <span className="text-muted-foreground">{timeAgo(r.createdAt)}</span> },
  ]
}

function RunsTab({ runs, total, onOpen }: { runs: RunSummary[]; total: number; onOpen: (r: RunSummary) => void }) {
  const [q, setQ] = useState("")
  const [mode, setMode] = useState("all")
  const [status, setStatus] = useState("all")
  const filtered = runs.filter((r) => {
    if (q && !r.externalRunId.toLowerCase().includes(q.toLowerCase())) return false
    if (mode !== "all" && r.mode !== mode) return false
    if (status !== "all" && r.status !== status) return false
    return true
  })
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 py-4">
          <div className="relative w-60">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-9" placeholder="搜索运行 ID" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Select value={mode} onValueChange={setMode}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部模式</SelectItem>
              <SelectItem value="eval_only">eval_only</SelectItem>
              <SelectItem value="pipeline">pipeline</SelectItem>
              <SelectItem value="run">run</SelectItem>
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="completed">completed</SelectItem>
              <SelectItem value="partial">partial</SelectItem>
              <SelectItem value="failed">failed</SelectItem>
              <SelectItem value="running">running</SelectItem>
            </SelectContent>
          </Select>
          <span className="ml-auto text-xs text-muted-foreground">共 {total} 条</span>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <DataTable columns={runColumns()} rows={filtered} rowKey={(r) => r.id} onRowClick={onOpen} empty="无匹配运行" />
        </CardContent>
      </Card>
    </div>
  )
}

function SamplesTab({ projectId }: { projectId: string }) {
  const [samples, setSamples] = useState<ProjectSample[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [trend, setTrend] = useState<SampleTrendPoint[]>([])

  useEffect(() => {
    api.listSamples(projectId).then(setSamples).catch(() => setSamples([]))
  }, [projectId])
  useEffect(() => {
    if (!selected) {
      setTrend([])
      return
    }
    api.sampleTrends(projectId, selected).then(setTrend).catch(() => setTrend([]))
  }, [projectId, selected])

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">样本（课件）</CardTitle>
          <span className="text-xs text-muted-foreground">点击查看走势</span>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={[
              { key: "externalSampleId", title: "样本", render: (s) => <span className="font-mono text-xs">{s.externalSampleId}</span> },
              { key: "evalCount", title: "评估次数", num: true, render: (s) => num(s.evalCount) },
              { key: "latestReward", title: "最近 Reward", num: true, render: (s) => fmt3(s.latestReward) },
              { key: "latestAt", title: "最近评估", render: (s) => <span className="text-muted-foreground">{timeAgo(s.latestAt)}</span> },
            ]}
            rows={samples}
            rowKey={(s) => s.externalSampleId}
            onRowClick={(s) => setSelected(s.externalSampleId)}
            empty="暂无样本"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{selected ? `走势：${selected}` : "样本走势"}</CardTitle>
        </CardHeader>
        <CardContent>
          {!selected ? (
            <div className="py-8 text-center text-sm text-muted-foreground">从左侧选择课件，查看其跨多次评估的 Reward 走势。</div>
          ) : trend.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">暂无走势数据</div>
          ) : (
            <MetricTrendChart
              points={trend.map((t) => ({
                label: new Date(t.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }),
                values: { Reward: t.reward },
              }))}
              series={[{ key: "Reward", name: METRIC_LABEL.Reward, color: "var(--chart-1)" }]}
              thresholds={[{ label: "达标 0.8", value: 0.8, color: "var(--chart-5)" }]}
              height={300}
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function SettingsTab({
  projectId,
  slug,
  name,
  description,
  isPublic,
  onPublicChanged,
  onArchived,
}: {
  projectId: string
  slug: string
  name: string
  description: string | null
  isPublic: boolean
  onPublicChanged: (v: boolean) => void
  onArchived: () => void
}) {
  const toast = useToast()
  const [panel, setPanel] = useState<SetTab>("keys")
  const items: [SetTab, string][] = [
    ["keys", "API Keys"],
    ["basic", "基本信息"],
    ["retention", "数据保留"],
    ["public", "公开访问"],
    ["danger", "危险区"],
  ]
  return (
    <div className="grid gap-4 md:grid-cols-[200px_minmax(0,1fr)]">
      <nav className="space-y-1">
        {items.map(([k, label]) => (
          <button
            key={k}
            onClick={() => setPanel(k)}
            className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
              panel === k ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"
            } ${k === "danger" ? "text-red-400" : ""}`}
          >
            {label}
          </button>
        ))}
      </nav>
      <div>
        {panel === "keys" && <KeysPanel projectId={projectId} slug={slug} />}
        {panel === "basic" && <BasicPanel name={name} slug={slug} description={description} onSave={() => toast.info("基本信息接口待后端接入")} />}
        {panel === "retention" && <RetentionPanel onSave={() => toast.info("数据保留接口待后端接入")} />}
        {panel === "public" && (
          <PublicPanel projectId={projectId} isPublic={isPublic} onChanged={onPublicChanged} />
        )}
        {panel === "danger" && <DangerPanel projectId={projectId} slug={slug} onArchived={onArchived} />}
      </div>
    </div>
  )
}

/** 公开访问面板：开启后该项目运行/样本详情页免登录可读，可被第三方 iframe 嵌入。 */
function PublicPanel({
  projectId,
  isPublic,
  onChanged,
}: {
  projectId: string
  isPublic: boolean
  onChanged: (v: boolean) => void
}) {
  const toast = useToast()
  const [saving, setSaving] = useState(false)
  async function toggle(next: boolean) {
    setSaving(true)
    try {
      await api.updateProject(projectId, { isPublic: next })
      onChanged(next)
      toast.success(next ? "已开启公开访问" : "已关闭公开访问")
    } catch (e) {
      const ex = e as { response?: { data?: { error?: string } }; message?: string }
      toast.error(ex.response?.data?.error || ex.message || "操作失败")
    } finally {
      setSaving(false)
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">公开访问</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="text-sm font-medium">{isPublic ? "已开启" : "未开启"}</div>
            <div className="text-xs text-muted-foreground">
              开启后，本项目的运行/样本详情页<b>免登录可读</b>，第三方系统可用 iframe 直接嵌入
              <code className="mx-1 rounded bg-muted px-1 py-0.5 font-mono">/run/&#123;id&#125;</code>页面。
            </div>
          </div>
          <Button variant={isPublic ? "default" : "outline"} disabled={saving} onClick={() => toggle(!isPublic)}>
            {saving ? "处理中…" : isPublic ? "关闭公开" : "开启公开"}
          </Button>
        </div>
        {isPublic && (
          <div className="rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-xs text-yellow-200">
            ⚠️ 公开后<b>任何持有链接的人都能查看</b>本项目下所有运行/样本（只读，不含 Key 与写操作）。
            请确认内容可对外可见后再开启。
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function KeysPanel({ projectId, slug }: { projectId: string; slug: string }) {
  const toast = useToast()
  const [keys, setKeys] = useState<ApiKeySafe[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [keyName, setKeyName] = useState("")
  const [issued, setIssued] = useState<IssuedApiKey | null>(null)
  const [deleteId, setDeleteId] = useState<ApiKeySafe | null>(null)
  const [creating, setCreating] = useState(false)

  async function load() {
    try {
      setKeys(await api.listKeys(projectId))
    } catch {
      /* ignore */
    }
  }
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  async function doCreate() {
    if (!keyName.trim()) {
      toast.error("请填写 Key 名称")
      return
    }
    setCreating(true)
    try {
      const k = await api.createKey(projectId, keyName.trim())
      setIssued(k)
      setCreateOpen(false)
      setKeyName("")
      load()
    } catch (e) {
      toast.error("签发失败：" + ((e as Error).message ?? ""))
    } finally {
      setCreating(false)
    }
  }
  async function doRevoke() {
    if (!deleteId) return
    try {
      await api.revokeKey(projectId, deleteId.id)
      toast.success("已删除")
      setDeleteId(null)
      load()
    } catch (e) {
      toast.error("删除失败：" + ((e as Error).message ?? ""))
    }
  }

  const snippetKey = keys.find((k) => !k.revokedAt)?.tokenPreview ?? "eval-••••••"
  const snippetText = `# 评估器侧环境变量（.env）
AGENT_EVAL_HOST=https://app.evalscope.io
AGENT_EVAL_API_KEY=${snippetKey}••••
AGENT_EVAL_PROJECT=${slug}`

  const activeKey = keys.find((k) => !k.revokedAt)
  const PLACEHOLDER_KEY = "<YOUR_API_KEY>"
  const mcpKey = issued?.token ?? PLACEHOLDER_KEY
  const serverUrl = `${window.location.origin}/api/v1/mcp`
  const mcpConfigs = buildMcpConfigs(serverUrl, mcpKey)
  const hasActiveKey = !!activeKey

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold">API Keys</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            评估器凭单一 API Key（Bearer）摄取数据。Key 仅创建时明文展示一次。
          </p>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" /> 新建 Key
        </Button>
      </div>

      <Card>
        <CardContent className="pt-6">
          <DataTable
            columns={[
              { key: "name", title: "名称", render: (k) => k.name || "—" },
              { key: "tokenPreview", title: "Key 前缀", render: (k) => <span className="font-mono text-xs text-muted-foreground">{k.tokenPreview}…</span> },
              { key: "callCount", title: "调用次数", num: true, render: (k) => num(Number(k.callCount || 0)) },
              { key: "lastUsedAt", title: "最近使用", render: (k) => <span className="text-muted-foreground">{k.lastUsedAt ? timeAgo(k.lastUsedAt) : "—"}</span> },
              {
                key: "status",
                title: "状态",
                render: (k) =>
                  k.revokedAt ? (
                    <SemPill tone="danger">已删除</SemPill>
                  ) : (
                    <SemPill tone="success">有效</SemPill>
                  ),
              },
              {
                key: "op",
                title: "",
                render: (k) =>
                  k.revokedAt ? null : (
                    <Button variant="outline" size="sm" className="text-red-400" onClick={() => setDeleteId(k)}>
                      <Trash2 className="size-3.5" /> 删除
                    </Button>
                  ),
              },
            ]}
            rows={keys.filter((k) => !k.revokedAt)}
            rowKey={(k) => k.id}
            empty="暂无 API Key"
          />
        </CardContent>
      </Card>

      <div>
        <h4 className="mb-2 text-sm font-medium">接入代码片段</h4>
        <pre className="overflow-x-auto rounded-lg border bg-secondary/40 p-3 font-mono text-xs leading-relaxed">
          {snippetText}
        </pre>
        <p className="mt-2 rounded-md border border-sky-500/30 bg-sky-500/5 p-2 text-xs text-muted-foreground">
          ResultSink 会在评估结束后自动以 Bearer Key 上报运行、样本、约束结论与制品文件。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">MCP 客户端配置</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            任意支持 Streamable HTTP 的 MCP 客户端（Claude Code / Cursor / Windsurf 等）可直接接入本项目。
          </p>
          <CopyRow label="Server URL" value={serverUrl} onCopy={() => toast.success("已复制 Server URL")} />
          <div className="space-y-3">
            <CodeBlock title="Claude Desktop — claude_desktop_config.json" code={mcpConfigs.claudeDesktop} />
            <CodeBlock title="Cherry Studio" code={mcpConfigs.cherryStudio} />
            <CodeBlock title="通用 / cURL 测试" code={mcpConfigs.generic} />
          </div>
          {!hasActiveKey ? (
            <div className="rounded-md border border-yellow-500/40 bg-yellow-500/5 p-3 text-xs text-yellow-200">
              ⚠️ 请先在上方创建 API Key，并将样例中的 <code className="font-mono">&lt;YOUR_API_KEY&gt;</code>{" "}
              替换为实际 Key。
            </div>
          ) : issued ? (
            <div className="rounded-md border border-green-500/40 bg-green-500/5 p-3 text-xs text-green-200">
              ✅ API Key 已填入下方样例，关闭弹窗后将恢复为 <code className="font-mono">&lt;YOUR_API_KEY&gt;</code> 占位符。
            </div>
          ) : (
            <div className="rounded-md border border-yellow-500/40 bg-yellow-500/5 p-3 text-xs text-yellow-200">
              ⚠️ 下方样例中的 <code className="font-mono">&lt;YOUR_API_KEY&gt;</code> 请替换为你的实际 Key。
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建 API Key</DialogTitle>
            <DialogDescription>为不同接入环境分别创建，便于独立删除</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="key-name">Key 名称</Label>
            <Input id="key-name" value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="如：ci-pipeline / staging" autoFocus />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button onClick={doCreate} disabled={creating}>{creating ? "创建中…" : "创建"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!issued} onOpenChange={(o) => !o && setIssued(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>API Key 已创建</DialogTitle>
          </DialogHeader>
          {issued && (
            <div className="space-y-3">
              <div className="rounded-md border border-yellow-500/40 bg-yellow-500/5 p-2 text-sm text-yellow-400">
                API Key 仅此次显示，关闭后无法再次查看，请立即保存。
              </div>
              <CopyRow label="API Key（Bearer）" value={issued.token} onCopy={() => toast.success("已复制 API Key")} />
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setIssued(null)}>我已保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteId} onOpenChange={(o) => !o && setDeleteId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除 API Key</DialogTitle>
            <DialogDescription>删除后使用该 Key 的接入将立即鉴权失败，且无法恢复。</DialogDescription>
          </DialogHeader>
          <div className="rounded-md border border-yellow-500/40 bg-yellow-500/5 p-2 text-sm">
            确认删除 Key <code className="rounded bg-muted px-1 font-mono">{deleteId?.name}</code>？相关环境需更换为新 Key。
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteId(null)}>取消</Button>
            <Button variant="destructive" onClick={doRevoke}>确认删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function CopyRow({ label, value, onCopy }: { label: string; value: string; onCopy: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input className="font-mono" readOnly value={value} />
        <Button
          size="sm"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value)
              setCopied(true)
              onCopy()
              setTimeout(() => setCopied(false), 1200)
            } catch {
              /* ignore */
            }
          }}
        >
          {copied ? "已复制" : "复制"}
        </Button>
      </div>
    </div>
  )
}

function buildMcpConfigs(serverUrl: string, token: string) {
  const claudeDesktop = JSON.stringify(
    {
      mcpServers: {
        evalscope: {
          url: serverUrl,
          headers: { Authorization: `Bearer ${token}` },
        },
      },
    },
    null,
    2,
  )
  const cherryStudio = JSON.stringify(
    {
      mcpServers: [
        {
          name: "EvalScope",
          url: serverUrl,
          headers: { Authorization: `Bearer ${token}` },
        },
      ],
    },
    null,
    2,
  )
  const generic = `# 环境变量方式
EVALSCOPE_MCP_URL=${serverUrl}
EVALSCOPE_MCP_TOKEN=${token}

# cURL 测试连接
curl -X POST ${serverUrl} \\
  -H "Authorization: Bearer ${token}" \\
  -H "Content-Type: application/json" \\
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}'`
  return { claudeDesktop, cherryStudio, generic }
}

function BasicPanel({ name, slug, description, onSave }: { name: string; slug: string; description: string | null; onSave: () => void }) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold">基本信息</h3>
        <p className="mt-1 text-sm text-muted-foreground">项目的名称、标识与默认评估配置。</p>
      </div>
      <div className="max-w-md space-y-4">
        <div className="space-y-2">
          <Label>项目名称</Label>
          <Input defaultValue={name} />
        </div>
        <div className="space-y-2">
          <Label>Slug</Label>
          <Input className="font-mono" defaultValue={slug} readOnly />
        </div>
        <div className="space-y-2">
          <Label>项目描述</Label>
          <textarea className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={3} defaultValue={description ?? ""} placeholder="一句话描述" />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline">重置</Button>
          <Button onClick={onSave}>保存更改</Button>
        </div>
      </div>
    </div>
  )
}

function RetentionPanel({ onSave }: { onSave: () => void }) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold">数据保留</h3>
        <p className="mt-1 text-sm text-muted-foreground">控制运行、样本与制品文件的存储时长。</p>
      </div>
      <div className="max-w-md space-y-4">
        <div className="space-y-2">
          <Label>运行 & 样本保留期</Label>
          <Select defaultValue="90">
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="30">30 天</SelectItem>
              <SelectItem value="90">90 天</SelectItem>
              <SelectItem value="180">180 天</SelectItem>
              <SelectItem value="365">365 天</SelectItem>
              <SelectItem value="-1">永久保留</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>制品文件保留期</Label>
          <Select defaultValue="30">
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="7">7 天</SelectItem>
              <SelectItem value="30">30 天</SelectItem>
              <SelectItem value="90">90 天</SelectItem>
              <SelectItem value="0">跟随样本</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="rounded-md border border-yellow-500/40 bg-yellow-500/5 p-2 text-xs text-muted-foreground">
          缩短保留期会在下次清理任务中删除超期数据，且不可恢复。
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline">重置</Button>
          <Button onClick={onSave}>保存更改</Button>
        </div>
      </div>
    </div>
  )
}

function DangerPanel({ projectId, slug, onArchived }: { projectId: string; slug: string; onArchived: () => void }) {
  const toast = useToast()
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [confirmSlug, setConfirmSlug] = useState("")

  async function doArchive() {
    try {
      await api.archiveProject(projectId)
      toast.success("已归档")
      setArchiveOpen(false)
      onArchived()
    } catch (e) {
      toast.error("归档失败：" + ((e as Error).message ?? ""))
    }
  }
  async function doDelete() {
    try {
      await api.deleteProject(projectId)
      toast.success("项目已删除")
      setDeleteOpen(false)
      onArchived()
    } catch (e) {
      toast.error("删除失败：" + ((e as Error).message ?? ""))
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold">危险区</h3>
        <p className="mt-1 text-sm text-muted-foreground">以下操作影响范围大或不可逆，请谨慎执行。</p>
      </div>
      <div className="max-w-2xl space-y-3">
        <Card>
          <CardContent className="flex items-center justify-between py-4">
            <div>
              <div className="text-sm font-medium">归档项目</div>
              <div className="text-xs text-muted-foreground">归档后不再出现在看板，数据保留，可恢复。</div>
            </div>
            <Button variant="outline" onClick={() => setArchiveOpen(true)}>归档</Button>
          </CardContent>
        </Card>
        <Card className="border-red-500/30">
          <CardContent className="flex items-center justify-between py-4">
            <div>
              <div className="text-sm font-medium text-red-400">删除项目</div>
              <div className="text-xs text-muted-foreground">永久删除项目及其全部运行、样本与制品，不可恢复。</div>
            </div>
            <Button variant="destructive" onClick={() => setDeleteOpen(true)}>删除项目</Button>
          </CardContent>
        </Card>
      </div>

      <Dialog open={archiveOpen} onOpenChange={setArchiveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>归档项目</DialogTitle>
            <DialogDescription>归档后项目不再出现在看板，数据保留。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiveOpen(false)}>取消</Button>
            <Button onClick={doArchive}>确认归档</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除项目</DialogTitle>
            <DialogDescription>此操作将永久删除项目及其全部运行、样本与制品，不可恢复。</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label>请输入项目 slug <code className="rounded bg-muted px-1 font-mono">{slug}</code> 以确认</Label>
            <Input className="font-mono" value={confirmSlug} onChange={(e) => setConfirmSlug(e.target.value)} placeholder={slug} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button>
            <Button variant="destructive" disabled={confirmSlug !== slug} onClick={doDelete}>永久删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
