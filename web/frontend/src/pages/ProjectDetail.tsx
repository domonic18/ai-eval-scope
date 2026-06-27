import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api } from "../api/client"
import type {
  ApiKeySafe,
  IssuedApiKey,
  ProjectSample,
  RunSummary,
  SampleTrendPoint,
  TrendPoint,
} from "../types"
import { fmt3, fmtMs, num, timeAgo } from "../lib/format"
import { METRIC_EXPLAIN, METRIC_LABEL, THRESHOLDS, metricColor, runBadge } from "../lib/eval"
import type { MetricKey } from "../lib/eval"
import {
  Badge,
  Button,
  Callout,
  CodeBlock,
  DataTable,
  Empty,
  Field,
  Input,
  Metric,
  Modal,
  Select,
  Tabs,
  TrendChart,
  useCrumbs,
  useToast,
} from "../components/ui"
import { IconDownload, IconPlus, IconTrash } from "../components/icons"

interface Project {
  id: string
  name: string
  slug: string
  description: string | null
  ruleSetVersion?: string | null
}

type Tab = "overview" | "runs" | "samples" | "settings"
type SetTab = "keys" | "basic" | "retention" | "danger"

function truncKey(k: string): string {
  if (!k) return "—"
  return k.length <= 16 ? k : `${k.slice(0, 12)}…${k.slice(-4)}`
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const { setCrumbs } = useCrumbs()

  const [project, setProject] = useState<Project | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runsTotal, setRunsTotal] = useState(0)
  const [trends, setTrends] = useState<TrendPoint[]>([])
  const [tab, setTab] = useState<Tab>("overview")

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
    api
      .projectTrends(id)
      .then(setTrends)
      .catch(() => setTrends([]))
  }, [id, setCrumbs])

  // 趋势按时间升序（左旧右新）
  const trendsAsc = useMemo(() => {
    return [...trends].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    )
  }, [trends])
  const latest = trendsAsc[trendsAsc.length - 1]
  const prev = trendsAsc[trendsAsc.length - 2]

  const deltaOf = (cur: number | undefined, prevV: number | undefined) => {
    if (cur == null) return null
    if (prevV == null) return <span className="muted">首次评估</span>
    const diff = cur - prevV
    if (Math.abs(diff) < 0.0005) return <span className="delta-flat">▬ 较上次持平</span>
    const arrow = diff > 0 ? "▲" : "▼"
    const cls = diff > 0 ? "delta-up" : "delta-down"
    return (
      <span className={cls}>
        {arrow} 较上次 {diff > 0 ? "+" : ""}
        {diff.toFixed(3)}
      </span>
    )
  }

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>
            {project ? project.name : "项目"}
            {project && (
              <Badge variant="success" dot="var(--success)" style={{ fontSize: 12, marginLeft: 4 }}>
                健康
              </Badge>
            )}
          </h1>
          <div className="sub">
            {project && (
              <>
                <code className="code-inline">{project.slug}</code> · {num(runsTotal)} 次运行
                {project.ruleSetVersion ? ` · 规则集 ${project.ruleSetVersion}` : ""}
              </>
            )}
          </div>
        </div>
        <div className="page-actions">
          <Button icon={<IconDownload size={15} />}>导出</Button>
        </div>
      </div>

      <div className="tabs r-2">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          items={[
            { key: "overview", label: "概览" },
            { key: "runs", label: "运行", count: num(runsTotal) },
            { key: "samples", label: "样本" },
            { key: "settings", label: "设置 & API Key" },
          ]}
        />
      </div>

      {tab === "overview" && (
        <div className="r-3">
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              gap: 14,
              marginBottom: 16,
            }}
          >
            {(["DR", "CPR", "Soft", "Pref", "Reward"] as MetricKey[]).map((k) => {
              const kk = k as "DR" | "CPR" | "Reward" | "Soft" | "Pref"
              const val = latest ? latest[kk] : undefined
              const prevVal = prev ? prev[kk] : undefined
              const delta = deltaOf(val, prevVal)
              return (
                <Metric
                  key={k}
                  label={METRIC_LABEL[k]}
                  value={fmt3(val)}
                  valueColor={metricColor(k, val)}
                  explain={METRIC_EXPLAIN[k]}
                  foot={
                    latest ? (
                      <span className="muted">
                        最近一次运行 {timeAgo(latest.created_at)}
                        {delta ? (
                          <>
                            {" · "}
                            {delta}
                          </>
                        ) : null}
                      </span>
                    ) : null
                  }
                />
              )
            })}
          </div>

          <div className="card trend-card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>指标趋势</h3>
            </div>
            <div className="card-body">
              {trendsAsc.length > 0 ? (
                <>
                  <LineTrendSVG trends={trendsAsc} />
                </>
              ) : (
                <Empty
                  title="暂无运行数据"
                  children={<>完成首次评估运行后，将在此展示 DR / CPR / Reward 趋势。</>}
                />
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>最近运行</h3>
              <a className="hint" style={{ cursor: "pointer" }} onClick={() => setTab("runs")}>
                查看全部 →
              </a>
            </div>
            <DataTable<RunSummary>
              columns={runColumns()}
              rows={runs.slice(0, 6)}
              rowKey={(r) => r.id}
              onRowClick={(r) => nav(`/run/${r.id}`)}
              empty={<span className="muted">暂无运行</span>}
            />
          </div>
        </div>
      )}

      {tab === "runs" && (
        <RunsTab runs={runs} total={runsTotal} onOpen={(r) => nav(`/run/${r.id}`)} />
      )}

      {tab === "samples" && id && <SamplesTab projectId={id} />}

      {tab === "settings" && project && (
        <SettingsTab
          projectId={project.id}
          slug={project.slug}
          name={project.name}
          description={project.description}
          onArchived={() => nav("/dashboard")}
        />
      )}
    </div>
  )
}

/** 趋势折线（DR/CPR/Reward）+ 图例。 */
function LineTrendSVG({ trends }: { trends: TrendPoint[] }) {
  const points = trends.map((t) => ({
    label: new Date(t.created_at).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" }),
    values: { DR: t.DR, CPR: t.CPR, Reward: t.Reward, Soft: t.Soft, Pref: t.Pref },
  }))
  const series = [
    { key: "DR", name: METRIC_LABEL.DR, color: "var(--success)" },
    { key: "CPR", name: METRIC_LABEL.CPR, color: "var(--warning)" },
    { key: "Reward", name: METRIC_LABEL.Reward, color: "var(--accent)" },
    { key: "Soft", name: METRIC_LABEL.Soft, color: "var(--signal)" },
    { key: "Pref", name: METRIC_LABEL.Pref, color: "var(--info)" },
  ]
  return (
    <TrendChart
      points={points}
      series={series}
      thresholds={[{ label: "综合评分达标 0.8", value: 0.8, color: "var(--accent)" }]}
    />
  )
}

function runColumns() {
  return [
    {
      key: "externalRunId",
      title: "运行",
      render: (r: RunSummary) => <span className="mono">#{r.externalRunId}</span>,
    },
    {
      key: "mode",
      title: "模式",
      render: (r: RunSummary) => <Badge variant="neutral">{r.mode}</Badge>,
    },
    {
      key: "status",
      title: "状态",
      render: (r: RunSummary) => {
        const b = runBadge(r.status)
        return (
          <Badge variant={b.variant} dot={b.dot} pulse={b.pulse}>
            {b.label}
          </Badge>
        )
      },
    },
    {
      key: "samples",
      title: "评估内容",
      render: (r: RunSummary) => {
        const ids = (r.samples ?? []).map((s) => s.externalSampleId)
        if (!ids.length) return <span className="muted">—</span>
        if (ids.length === 1) return <span className="mono">{ids[0]}</span>
        return (
          <span className="mono">
            {ids[0]} <span className="muted">+{ids.length - 1}</span>
          </span>
        )
      },
    },
    {
      key: "dr",
      title: METRIC_LABEL.DR,
      num: true,
      render: (r: RunSummary) => <span className={r.dr >= 0.95 ? "t-add" : ""}>{fmt3(r.dr)}</span>,
    },
    { key: "cpr", title: METRIC_LABEL.CPR, num: true, render: (r: RunSummary) => fmt3(r.cpr) },
    { key: "avgReward", title: METRIC_LABEL.Reward, num: true, render: (r: RunSummary) => fmt3(r.avgReward) },
    {
      key: "createdAt",
      title: "时间",
      render: (r: RunSummary) => <span className="muted">{timeAgo(r.createdAt)}</span>,
    },
  ]
}

/** 运行 Tab：客户端筛选 + 分页表。 */
function RunsTab({
  runs,
  total,
  onOpen,
}: {
  runs: RunSummary[]
  total: number
  onOpen: (r: RunSummary) => void
}) {
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
    <div className="r-3">
      <div className="card" style={{ marginBottom: 16 }}>
        <div
          className="card-body"
          style={{
            padding: "14px 16px",
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <div className="input-icon-wrap" style={{ width: 240, position: "relative" }}>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              width={16}
              height={16}
              style={{
                position: "absolute",
                left: 12,
                top: "50%",
                transform: "translateY(-50%)",
                color: "var(--text-tertiary)",
              }}
            >
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <Input
              className="input"
              style={{ paddingLeft: 38 }}
              placeholder="搜索运行 ID"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <Select style={{ width: "auto" }} value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="all">全部模式</option>
            <option value="eval_only">eval_only</option>
            <option value="pipeline">pipeline</option>
            <option value="run">run</option>
          </Select>
          <Select
            style={{ width: "auto" }}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">全部状态</option>
            <option value="completed">completed</option>
            <option value="partial">partial</option>
            <option value="failed">failed</option>
            <option value="running">running</option>
          </Select>
          <span style={{ marginLeft: "auto" }} className="muted">
            共 <span className="mono">{total}</span> 条
          </span>
        </div>
      </div>
      <div className="card">
        <DataTable<RunSummary>
          columns={[
            ...runColumns().slice(0, 3),
            {
              key: "ruleSetVersion",
              title: "规则集",
              render: (r: RunSummary) => (
                <span className="mono muted">{r.ruleSetVersion ?? "—"}</span>
              ),
            },
            ...runColumns().slice(3),
            {
              key: "avgTimeMs",
              title: "耗时",
              num: true,
              render: (r: RunSummary) => <span className="muted">{fmtMs(r.avgTimeMs)}</span>,
            },
          ]}
          rows={filtered}
          rowKey={(r) => r.id}
          onRowClick={onOpen}
          pageSize={15}
          empty={<span className="muted">无匹配运行</span>}
        />
      </div>
    </div>
  )
}

/** 样本 Tab：项目下课件清单 + 选中课件跨 run 走势（docs/arch/14）。 */
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

  const rewards = trend.map((t) => t.reward)
  const lo = rewards.length ? Math.min(...rewards) : 0
  const hi = rewards.length ? Math.max(...rewards) : 1

  return (
    <div
      className="r-3"
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(340px,1fr) minmax(360px,1.2fr)",
        gap: 16,
      }}
    >
      <div className="card">
        <div className="card-head">
          <h3>样本（课件）</h3>
          <span className="hint">点击查看走势</span>
        </div>
        <DataTable<ProjectSample>
          columns={[
            {
              key: "externalSampleId",
              title: "样本（逻辑标识）",
              render: (s) => <span className="mono">{s.externalSampleId}</span>,
            },
            {
              key: "evalCount",
              title: "评估次数",
              num: true,
              render: (s) => num(s.evalCount),
            },
            {
              key: "latestReward",
              title: "最近 Reward",
              num: true,
              render: (s) => (
                <span className={s.latestReward >= 0.8 ? "t-add" : ""}>{fmt3(s.latestReward)}</span>
              ),
            },
            {
              key: "latestAt",
              title: "最近评估",
              render: (s) => <span className="muted">{timeAgo(s.latestAt)}</span>,
            },
          ]}
          rows={samples}
          rowKey={(s) => s.externalSampleId}
          onRowClick={(s) => setSelected(s.externalSampleId)}
          pageSize={15}
          empty={<span className="muted">暂无样本</span>}
        />
      </div>

      <div className="card">
        <div className="card-head">
          <h3>{selected ? `走势：${selected}` : "样本走势"}</h3>
          {trend.length > 0 && (
            <span className="hint">
              Reward {fmt3(lo)}–{fmt3(hi)} · {trend.length} 次评估
            </span>
          )}
        </div>
        <div className="card-body">
          {!selected ? (
            <Empty title="选择一个样本" children={<>从左侧选择课件，查看其跨多次评估的 Reward 走势。</>} />
          ) : trend.length === 0 ? (
            <Empty title="暂无走势数据" />
          ) : (
            <>
              <div style={{ marginBottom: 16 }}>
                <TrendChart
                  points={trend.map((t) => ({
                    label: new Date(t.created_at).toLocaleString("zh-CN", {
                      month: "numeric",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    }),
                    values: { Reward: t.reward },
                  }))}
                  series={[{ key: "Reward", name: METRIC_LABEL.Reward, color: "var(--accent)" }]}
                  height={300}
                  thresholds={[{ label: "达标 0.8", value: 0.8, color: "var(--success)" }]}
                />
              </div>
              <DataTable<SampleTrendPoint>
                columns={[
                  {
                    key: "created_at",
                    title: "时间",
                    render: (t) => (
                      <span className="muted">
                        {new Date(t.created_at).toLocaleString("zh-CN")}
                      </span>
                    ),
                  },
                  {
                    key: "run_id",
                    title: "运行",
                    render: (t) => <span className="mono">#{t.run_id.slice(-8)}</span>,
                  },
                  {
                    key: "reward",
                    title: "Reward",
                    num: true,
                    render: (t) => (
                      <span className={t.reward >= 0.8 ? "t-add" : ""}>{fmt3(t.reward)}</span>
                    ),
                  },
                  {
                    key: "s_format",
                    title: "S_format",
                    num: true,
                    render: (t) => fmt3(t.s_format),
                  },
                  {
                    key: "s_common",
                    title: "S_common",
                    num: true,
                    render: (t) => fmt3(t.s_common),
                  },
                  {
                    key: "content_hash",
                    title: "内容版本",
                    render: (t) =>
                      t.content_hash ? (
                        <span className="mono muted">{t.content_hash}</span>
                      ) : (
                        <span className="muted">—</span>
                      ),
                  },
                ]}
                rows={[...trend].reverse()}
                rowKey={(t) => t.run_id}
                pageSize={20}
                empty={<span className="muted">无数据</span>}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** 设置 Tab：左侧子导航 + 四面板。 */
function SettingsTab({
  projectId,
  slug,
  name,
  description,
  onArchived,
}: {
  projectId: string
  slug: string
  name: string
  description: string | null
  onArchived: () => void
}) {
  const toast = useToast()
  const [panel, setPanel] = useState<SetTab>("keys")

  return (
    <div className="settings-grid r-3">
      <div className="set-side">
        {(
          [
            ["keys", "API Keys"],
            ["basic", "基本信息"],
            ["retention", "数据保留"],
            ["danger", "危险区"],
          ] as [SetTab, string][]
        ).map(([k, label]) => (
          <a
            key={k}
            className={`set-nav ${panel === k ? "active" : ""}`}
            style={k === "danger" ? { color: "var(--danger)" } : undefined}
            onClick={() => setPanel(k)}
          >
            {label}
          </a>
        ))}
      </div>

      <div className="set-main">
        {panel === "keys" && <KeysPanel projectId={projectId} slug={slug} />}
        {panel === "basic" && (
          <BasicPanel
            name={name}
            slug={slug}
            description={description}
            onSave={() => toast.info("基本信息接口待后端接入")}
          />
        )}
        {panel === "retention" && (
          <RetentionPanel onSave={() => toast.info("数据保留接口待后端接入")} />
        )}
        {panel === "danger" && (
          <DangerPanel projectId={projectId} slug={slug} onArchived={onArchived} />
        )}
      </div>
    </div>
  )
}

function KeysPanel({ projectId, slug }: { projectId: string; slug: string }) {
  const toast = useToast()
  const [keys, setKeys] = useState<ApiKeySafe[]>([])
  const [, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [keyName, setKeyName] = useState("")
  const [issued, setIssued] = useState<IssuedApiKey | null>(null)
  const [deleteId, setDeleteId] = useState<ApiKeySafe | null>(null)
  const [creating, setCreating] = useState(false)

  async function load() {
    setLoading(true)
    try {
      setKeys(await api.listKeys(projectId))
    } finally {
      setLoading(false)
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

  const snippetKey = keys.find((k) => !k.revokedAt)?.publicKey ?? "pk_live_••••••••"
  const snippetText = `# 评估器侧环境变量（.env）
AGENT_EVAL_INGEST_URL=https://app.evalscope.io/api/public/ingest
AGENT_EVAL_PUBLIC_KEY=${snippetKey}
AGENT_EVAL_SECRET_KEY=sk_live_••••••••••••••••
AGENT_EVAL_PROJECT=${slug}`

  return (
    <>
      <div className="spread" style={{ marginBottom: 6 }}>
        <h3 style={{ fontSize: 16, fontWeight: 650 }}>API Keys</h3>
        <Button
          variant="primary"
          size="sm"
          icon={<IconPlus size={13} />}
          onClick={() => setCreateOpen(true)}
        >
          新建 Key
        </Button>
      </div>
      <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>
        评估器（ResultSink）凭 Key 的 HMAC 签名摄取数据。Secret 仅在创建时明文展示一次。
      </p>

      <div className="card" style={{ marginBottom: 24 }}>
        <DataTable<ApiKeySafe>
          columns={[
            { key: "name", title: "名称", render: (k) => k.name || "—" },
            {
              key: "publicKey",
              title: "公钥",
              render: (k) => <span className="mono muted">{truncKey(k.publicKey)}</span>,
            },
            {
              key: "callCount",
              title: "调用次数",
              num: true,
              render: (k) => num(Number(k.callCount || 0)),
            },
            {
              key: "lastUsedAt",
              title: "最近使用",
              render: (k) => (
                <span className="muted">{k.lastUsedAt ? timeAgo(k.lastUsedAt) : "—"}</span>
              ),
            },
            {
              key: "status",
              title: "状态",
              render: (k) =>
                k.revokedAt ? (
                  <Badge variant="danger">已删除</Badge>
                ) : (
                  <Badge variant="success">有效</Badge>
                ),
            },
            {
              key: "op",
              title: "",
              render: (k) =>
                k.revokedAt ? null : (
                  <div style={{ textAlign: "right" }}>
                    <Button
                      variant="danger"
                      size="sm"
                      icon={<IconTrash size={13} />}
                      onClick={() => setDeleteId(k)}
                    >
                      删除
                    </Button>
                  </div>
                ),
            },
          ]}
          rows={keys.filter((k) => !k.revokedAt)}
          rowKey={(k) => k.id}
          empty={<span className="muted">暂无 API Key</span>}
        />
      </div>

      <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>接入代码片段</h3>
      <CodeBlock text={snippetText}>
        {snippetText.split("\n").map((line, i) => {
          if (line.startsWith("#"))
            return (
              <div key={i} style={{ color: "var(--text-quaternary)" }}>
                {line}
              </div>
            )
          const eq = line.indexOf("=")
          if (eq < 0) return <div key={i}>{line}</div>
          return (
            <div key={i}>
              <span style={{ color: "var(--accent)" }}>{line.slice(0, eq)}</span>
              <span style={{ color: "var(--text-secondary)" }}>=</span>
              <span style={{ color: "var(--signal)" }}>{line.slice(eq + 1)}</span>
            </div>
          )
        })}
      </CodeBlock>
      <div className="callout callout-info" style={{ marginTop: 12 }}>
        ResultSink 会在评估结束后自动以 HMAC-SHA256 签名上报运行、样本、约束结论与制品文件。
      </div>

      {/* 命名弹窗 */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="新建 API Key"
        desc="为不同接入环境分别创建，便于独立删除"
        footer={
          <>
            <Button onClick={() => setCreateOpen(false)}>取消</Button>
            <Button variant="primary" onClick={doCreate} disabled={creating}>
              {creating ? "创建中…" : "创建"}
            </Button>
          </>
        }
      >
        <Field label="Key 名称" help="仅用于识别用途，不影响权限" style={{ marginBottom: 0 }}>
          <Input
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
            placeholder="如：ci-pipeline / staging"
            autoFocus
          />
        </Field>
      </Modal>

      {/* 一次性密钥展示 */}
      <Modal
        open={!!issued}
        onClose={() => setIssued(null)}
        title="API Key 已创建"
        width={540}
        footer={
          <Button variant="primary" onClick={() => setIssued(null)}>
            我已保存
          </Button>
        }
      >
        {issued && (
          <>
            <Callout variant="warn" style={{ marginBottom: 18 }}>
              Secret 仅此次显示，关闭后无法再次查看，请立即保存。
            </Callout>
            <Field label="公钥 Public Key">
              <CopyRow value={issued.publicKey} onCopy={() => toast.success("已复制公钥")} />
            </Field>
            <Field label="密钥 Secret Key" style={{ marginBottom: 0 }}>
              <CopyRow value={issued.secretKey} onCopy={() => toast.success("已复制 Secret")} />
            </Field>
          </>
        )}
      </Modal>

      {/* 删除确认 */}
      <Modal
        open={!!deleteId}
        onClose={() => setDeleteId(null)}
        title="删除 API Key"
        desc="删除后使用该 Key 的接入将立即鉴权失败，且无法恢复。"
        footer={
          <>
            <Button onClick={() => setDeleteId(null)}>取消</Button>
            <Button variant="danger" onClick={doRevoke}>
              确认删除
            </Button>
          </>
        }
      >
        <Callout variant="warn">
          确认删除 Key <code className="code-inline">{deleteId?.name}</code>？相关环境需更换为新
          Key。
        </Callout>
      </Modal>
    </>
  )
}

function CopyRow({ value, onCopy }: { value: string; onCopy: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="row">
      <Input className="mono" readOnly value={value} />
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
  )
}

function BasicPanel({
  name,
  slug,
  description,
  onSave,
}: {
  name: string
  slug: string
  description: string | null
  onSave: () => void
}) {
  return (
    <>
      <h3 style={{ fontSize: 16, fontWeight: 650, marginBottom: 4 }}>基本信息</h3>
      <p className="muted" style={{ fontSize: 13, marginBottom: 20 }}>
        项目的名称、标识与默认评估配置。
      </p>
      <div style={{ maxWidth: 520 }}>
        <Field label="项目名称">
          <Input defaultValue={name} />
        </Field>
        <Field label="Slug（项目唯一标识）" help="用于接入标识与 URL，创建后不建议修改。">
          <Input className="mono" defaultValue={slug} readOnly />
        </Field>
        <Field label="项目描述">
          <textarea
            className="input"
            rows={3}
            defaultValue={description ?? ""}
            placeholder="一句话描述这个项目评估的 Agent 与场景"
          />
        </Field>
        <div className="row" style={{ justifyContent: "flex-end", gap: 10, marginTop: 8 }}>
          <Button>重置</Button>
          <Button variant="primary" onClick={onSave}>
            保存更改
          </Button>
        </div>
      </div>
    </>
  )
}

function RetentionPanel({ onSave }: { onSave: () => void }) {
  return (
    <>
      <h3 style={{ fontSize: 16, fontWeight: 650, marginBottom: 4 }}>数据保留</h3>
      <p className="muted" style={{ fontSize: 13, marginBottom: 20 }}>
        控制运行、样本与制品文件的存储时长。超过保留期的数据将被自动清理以节省存储。
      </p>
      <div style={{ maxWidth: 520 }}>
        <Field
          label="运行 & 样本数据保留期"
          help="指标聚合结果始终保留；仅清理明细样本与约束结论。"
        >
          <Select defaultValue="90">
            <option value="30">30 天</option>
            <option value="90">90 天</option>
            <option value="180">180 天</option>
            <option value="365">365 天</option>
            <option value="-1">永久保留</option>
          </Select>
        </Field>
        <Field
          label="制品文件保留期（文档 / 截图 / Trace）"
          help="制品占用对象存储空间最大，建议短于样本保留期。"
        >
          <Select defaultValue="30">
            <option value="7">7 天</option>
            <option value="30">30 天</option>
            <option value="90">90 天</option>
            <option value="0">跟随样本</option>
          </Select>
        </Field>
        <Callout variant="warn" style={{ margin: "4px 0 16px" }}>
          缩短保留期会在下次清理任务中删除超期数据，且不可恢复。
        </Callout>
        <div className="row" style={{ justifyContent: "flex-end", gap: 10 }}>
          <Button>重置</Button>
          <Button variant="primary" onClick={onSave}>
            保存更改
          </Button>
        </div>
      </div>
    </>
  )
}

function DangerPanel({
  projectId,
  slug,
  onArchived,
}: {
  projectId: string
  slug: string
  onArchived: () => void
}) {
  const toast = useToast()
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [, setArchiving] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [confirmSlug, setConfirmSlug] = useState("")

  async function doArchive() {
    setArchiving(true)
    try {
      await api.archiveProject(projectId)
      toast.success("已归档")
      setArchiveOpen(false)
      onArchived()
    } catch (e) {
      toast.error("归档失败：" + ((e as Error).message ?? ""))
    } finally {
      setArchiving(false)
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
    <>
      <h3 style={{ fontSize: 16, fontWeight: 650, marginBottom: 4 }}>危险区</h3>
      <p className="muted" style={{ fontSize: 13, marginBottom: 20 }}>
        以下操作影响范围大或不可逆，请谨慎执行。
      </p>
      <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="card">
          <div className="card-body spread">
            <div>
              <div style={{ fontWeight: 600, fontSize: 13.5, marginBottom: 2 }}>归档项目</div>
              <div className="muted" style={{ fontSize: 12.5 }}>
                归档后不再出现在看板，数据保留，可随时恢复。
              </div>
            </div>
            <Button onClick={() => setArchiveOpen(true)}>归档</Button>
          </div>
        </div>
        <div className="card" style={{ borderColor: "rgba(248,81,73,0.3)" }}>
          <div className="card-body spread">
            <div>
              <div
                style={{ fontWeight: 600, fontSize: 13.5, marginBottom: 2, color: "var(--danger)" }}
              >
                删除项目
              </div>
              <div className="muted" style={{ fontSize: 12.5 }}>
                永久删除项目及其全部运行、样本与制品，
                <b style={{ color: "var(--text-secondary)" }}>不可恢复</b>。
              </div>
            </div>
            <Button variant="danger" onClick={() => setDeleteOpen(true)}>
              删除项目
            </Button>
          </div>
        </div>
      </div>

      <Modal
        open={archiveOpen}
        onClose={() => setArchiveOpen(false)}
        title="归档项目"
        desc="归档后项目不再出现在看板，数据保留。"
        footer={
          <>
            <Button onClick={() => setArchiveOpen(false)}>取消</Button>
            <Button variant="primary" onClick={doArchive}>
              确认归档
            </Button>
          </>
        }
      >
        <Callout variant="info">归档后可由管理员恢复。</Callout>
      </Modal>

      <Modal
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        title="删除项目"
        desc="此操作将永久删除项目及其全部运行、样本与制品，不可恢复。"
        footer={
          <>
            <Button onClick={() => setDeleteOpen(false)}>取消</Button>
            <Button variant="danger" disabled={confirmSlug !== slug} onClick={doDelete}>
              永久删除
            </Button>
          </>
        }
      >
        <Field
          label={
            <>
              请输入项目 slug <code className="code-inline">{slug}</code> 以确认
            </>
          }
          style={{ marginBottom: 0 }}
        >
          <Input
            className="mono"
            value={confirmSlug}
            onChange={(e) => setConfirmSlug(e.target.value)}
            placeholder={slug}
          />
        </Field>
      </Modal>
    </>
  )
}
