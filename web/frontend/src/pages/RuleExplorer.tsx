/**
 * 评测规则浏览器 — 完整查看评估规则集/提示词/参考数据/聚合策略/指标定义。
 *
 * 左侧资产树导航 + 右侧详情面板（5 种视图），数据来自后端 *_assets.content JSONB
 * 和 /scenarios/:id/defaults。只读查看（非编辑），用于理解评测如何运作。
 */

/* 行业最佳实践滚动条：深色模式下高对比、宽 8px、带 track 背景 */
<style>{`
  .scroll-area {
    scrollbar-width: auto;
    scrollbar-color: #4a5060 var(--bg-inset);
  }
  .scroll-area::-webkit-scrollbar { width: 8px; height: 8px; }
  .scroll-area::-webkit-scrollbar-track {
    background: var(--bg-inset);
    border-radius: 4px;
  }
  .scroll-area::-webkit-scrollbar-thumb {
    background: #3a3f4b;
    border-radius: 4px;
    border: 1px solid #4a5060;
  }
  .scroll-area::-webkit-scrollbar-thumb:hover {
    background: #565c6a;
  }
  .scroll-area::-webkit-scrollbar-corner { background: var(--bg-inset); }
`}</style>

import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { useCrumbs } from "../components/AppShell"
import { Page, PageHead, TierChip } from "../components/shared"
import { Card, CardContent, CardHeader, CardTitle } from "../components/shadcn/card"
import { Badge } from "../components/shadcn/badge"
import { Button } from "../components/shadcn/button"
import { api, type AssetKind, type CatalogEntry } from "../api/client"
import type { MetricDef, MetricExplainRow } from "../types"
import {
  BookOpen,
  ChevronRight,
  Database,
  FileText,
  Gauge,
  Layers,
} from "lucide-react"

type Selection =
  | { type: "rule-set"; assetId: string }
  | { type: "prompt"; assetId: string }
  | { type: "dataset"; assetId: string }
  | { type: "policy" }
  | { type: "metrics" }

export default function RuleExplorer() {
  const { id = "" } = useParams<{ id: string }>()
  const { setCrumbs } = useCrumbs()
  const [catalog, setCatalog] = useState<{
    rule_sets: CatalogEntry[]
    prompts: CatalogEntry[]
    datasets: CatalogEntry[]
  } | null>(null)
  const [defs, setDefs] = useState<MetricDef[]>([])
  const [hasPolicy, setHasPolicy] = useState(false)
  const [sel, setSel] = useState<Selection | null>(null)

  useEffect(() => {
    setCrumbs([
      { label: "配置中心", to: "/config" },
      { label: id, to: `/config/scenarios/${id}` },
      { label: "评测规则" },
    ])
    Promise.all([api.scenarioCatalog(id), api.scenarioDefaults(id), api.scenarioAggregationPolicy(id)])
      .then(([c, d, p]) => {
        setCatalog(c)
        setDefs(d)
        setHasPolicy(!!p)
        if (c.rule_sets.length) setSel({ type: "rule-set", assetId: c.rule_sets[0].asset_id })
      })
      .catch(() => {})
  }, [id, setCrumbs])

  return (
    <Page>
      <PageHead
        title="评测规则浏览器"
        sub="完整查看本次评估使用的规则集、提示词、参考数据、聚合策略与指标定义"
      />
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        {/* ── 左侧资产树 ── */}
        <Card className="h-fit">
          <CardContent className="p-4 space-y-5">
            <TreeSection icon={Layers} label="规则集">
              {catalog?.rule_sets.map((r) => (
                <TreeItem
                  key={r.asset_id}
                  active={sel?.type === "rule-set" && sel.assetId === r.asset_id}
                  icon={FileText}
                  name={r.asset_id}
                  version={r.version}
                  onClick={() => setSel({ type: "rule-set", assetId: r.asset_id })}
                />
              ))}
            </TreeSection>
            <TreeSection icon={BookOpen} label="提示词">
              {catalog?.prompts.map((p) => (
                <TreeItem
                  key={p.asset_id}
                  active={sel?.type === "prompt" && sel.assetId === p.asset_id}
                  icon={FileText}
                  name={p.asset_id}
                  onClick={() => setSel({ type: "prompt", assetId: p.asset_id })}
                />
              ))}
            </TreeSection>
            <TreeSection icon={Database} label="参考数据">
              {catalog?.datasets.map((d) => (
                <TreeItem
                  key={d.asset_id}
                  active={sel?.type === "dataset" && sel.assetId === d.asset_id}
                  icon={Database}
                  name={d.asset_id}
                  version={d.version}
                  onClick={() => setSel({ type: "dataset", assetId: d.asset_id })}
                />
              ))}
            </TreeSection>
            {hasPolicy && (
              <TreeSection icon={Gauge} label="聚合策略">
                <TreeItem
                  active={sel?.type === "policy"}
                  icon={Gauge}
                  name="courseware-default"
                  onClick={() => setSel({ type: "policy" })}
                />
              </TreeSection>
            )}
            <TreeSection icon={Layers} label={`指标定义 (${defs.length})`}>
              <TreeItem
                active={sel?.type === "metrics"}
                icon={Layers}
                name="全部指标"
                onClick={() => setSel({ type: "metrics" })}
              />
            </TreeSection>
          </CardContent>
        </Card>

        {/* ── 右侧详情面板 ── */}
        <div>
          {sel?.type === "rule-set" && <RuleSetDetail scenarioId={id} assetId={sel.assetId} />}
          {sel?.type === "prompt" && <PromptDetail scenarioId={id} assetId={sel.assetId} />}
          {sel?.type === "dataset" && <DatasetDetail scenarioId={id} assetId={sel.assetId} />}
          {sel?.type === "policy" && <PolicyDetail scenarioId={id} />}
          {sel?.type === "metrics" && <MetricsDetail defs={defs} />}
        </div>
      </div>
    </Page>
  )
}

// ── 资产树组件 ──

function TreeSection({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon className="size-3.5" />
        {label}
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

function TreeItem({
  active,
  icon: Icon,
  name,
  version,
  onClick,
}: {
  active: boolean
  icon: React.ComponentType<{ className?: string }>
  name: string
  version?: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors ${
        active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"
      }`}
    >
      <Icon className="size-3.5 shrink-0 opacity-70" />
      <span className="flex-1 truncate font-mono text-xs">{name}</span>
      {version && <span className="shrink-0 text-[10px] text-muted-foreground/60">{version}</span>}
      {active && <ChevronRight className="size-3 shrink-0" />}
    </button>
  )
}

// ── 1. 规则集详情 ──

function RuleSetDetail({ scenarioId, assetId }: { scenarioId: string; assetId: string }) {
  const [content, setContent] = useState<Record<string, any> | null>(null)
  useEffect(() => {
    api.assetContent(scenarioId, "rule-sets", assetId).then(setContent).catch(() => setContent(null))
  }, [scenarioId, assetId])

  if (!content) return <LoadingCard />
  const rules = content.rules ?? []
  const cascade = content.cascade ?? []
  const dims = content.dimensions ?? []

  return (
    <div className="space-y-4">
      <DetailHeader title={assetId} sub={content.description ?? ""} meta={[
        { label: "规则数", value: String(rules.length) },
        { label: "阶段", value: cascade.map((c: any) => c.stage).join(" → ") },
        { label: "维度", value: dims.map((d: any) => d.id).join(", ") },
      ]} />

      {/* 级联流程 */}
      <Card>
        <CardHeader><CardTitle className="text-sm">级联流程</CardTitle></CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-2">
            {cascade.map((c: any, i: number) => (
              <div key={c.stage} className="flex items-center gap-2">
                {i > 0 && <ChevronRight className="size-4 text-muted-foreground" />}
                <div className={`rounded-md border px-3 py-1.5 text-sm ${c.stop_on_fail ? "border-red-500/40 text-red-400" : "border-border text-muted-foreground"}`}>
                  {c.name ?? c.stage}
                  {c.stop_on_fail && <span className="ml-1.5 text-[10px]">短路</span>}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 规则列表 */}
      <div className="space-y-2">
        {rules.map((r: any) => (
          <RuleCard key={r.id} rule={r} />
        ))}
      </div>
    </div>
  )
}

function RuleCard({ rule }: { rule: any }) {
  const tier = rule.evaluator?.split(".")[0] ?? rule.stage
  const tierMap: Record<string, "hard" | "soft" | "pref"> = {
    format: "hard", commonsense: "hard", soft: "soft", pref: "pref", vision: "soft",
  }
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">{rule.id}</span>
              <span className="text-sm font-medium">{rule.name}</span>
            </div>
            {rule.description && <p className="mt-1 text-xs text-muted-foreground">{rule.description}</p>}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{rule.evaluator}</span>
              {rule.params?.template_id && (
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  prompt: {rule.params.template_id}
                </span>
              )}
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                stage: {rule.stage}
              </span>
            </div>
          </div>
          <TierChip tier={tierMap[tier] ?? "hard"}>{tier}</TierChip>
        </div>
      </CardContent>
    </Card>
  )
}

// ── 2. 提示词详情 ──

function PromptDetail({ scenarioId, assetId }: { scenarioId: string; assetId: string }) {
  const [content, setContent] = useState<Record<string, any> | null>(null)
  useEffect(() => {
    api.assetContent(scenarioId, "prompts", assetId).then(setContent).catch(() => setContent(null))
  }, [scenarioId, assetId])

  if (!content) return <LoadingCard />
  const vars = content.dimensions ?? []
  return (
    <div className="space-y-4">
      <DetailHeader title={content.template_id ?? assetId} sub={content.name ?? ""} meta={[
        { label: "temperature", value: String(content.temperature ?? "—") },
        { label: "seed", value: String(content.seed ?? "—") },
        { label: "维度", value: String(vars.length) },
      ]} />

      {content.system_prompt && (
        <CodeBlock label="System Prompt" content={content.system_prompt} />
      )}
      {content.user_prompt_template && (
        <CodeBlock label="User Prompt Template（Jinja2）" content={content.user_prompt_template} highlightVars />
      )}

      {vars.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">评分维度（output_schema）</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-1">
              {vars.map((v: any) => (
                <div key={v.dim_id} className="flex items-center gap-3 border-t py-2 text-sm first:border-t-0">
                  <span className="w-28 shrink-0 font-mono text-xs text-muted-foreground">{v.dim_id}</span>
                  <span className="flex-1">{v.name}</span>
                  <span className="text-xs text-muted-foreground">w={v.weight}</span>
                  <span className="text-xs text-muted-foreground">{JSON.stringify(v.score_range ?? "—")}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ── 3. 数据集详情 ──

function DatasetDetail({ scenarioId, assetId }: { scenarioId: string; assetId: string }) {
  const [content, setContent] = useState<Record<string, any> | null>(null)
  useEffect(() => {
    api.assetContent(scenarioId, "datasets", assetId).then(setContent).catch(() => setContent(null))
  }, [scenarioId, assetId])

  if (!content) return <LoadingCard />
  const constants = content.constants ?? []
  const misconceptions = content.misconceptions ?? []

  return (
    <div className="space-y-4">
      <DetailHeader title={assetId} sub={content.description ?? `subject: ${content.subject ?? "—"}`} meta={[
        { label: "constants", value: String(constants.length) },
        { label: "misconceptions", value: String(misconceptions.length) },
      ]} />

      {constants.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">常量/公式（{constants.length}）</CardTitle></CardHeader>
          <CardContent>
            <div className="scroll-area max-h-[280px] space-y-1 overflow-y-auto rounded bg-muted/20 p-2 pr-1">
              {constants.map((c: any, i: number) => (
                <div key={i} className="flex items-start gap-3 border-t py-2 text-sm first:border-t-0">
                  <span className="min-w-0 flex-1 truncate">{c.name}</span>
                  <span className="shrink-0 font-mono text-xs text-emerald-400">{c.value}</span>
                  {c.tolerance && <span className="shrink-0 text-[10px] text-muted-foreground">±{c.tolerance}</span>}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {misconceptions.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">常见误区（{misconceptions.length}）</CardTitle></CardHeader>
          <CardContent>
            <div className="scroll-area max-h-[280px] space-y-1 overflow-y-auto rounded bg-muted/20 p-2 pr-1">
              {misconceptions.map((m: any, i: number) => (
                <div key={i} className="flex items-start gap-3 border-t py-2 text-sm first:border-t-0">
                  <Badge variant={m.severity === "error" ? "destructive" : "secondary"} className="shrink-0 text-[10px]">
                    {m.severity ?? "warning"}
                  </Badge>
                  <span className="min-w-0 flex-1">
                    <span className="font-mono text-xs text-muted-foreground">{m.pattern}</span>
                    {m.correct && <span className="ml-2 text-emerald-400">→ {m.correct}</span>}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ── 4. 聚合策略详情 ──

function PolicyDetail({ scenarioId }: { scenarioId: string }) {
  const [policy, setPolicy] = useState<Record<string, any> | null>(null)
  useEffect(() => {
    api.scenarioAggregationPolicy(scenarioId).then(setPolicy).catch(() => setPolicy(null))
  }, [scenarioId])

  if (!policy) return <LoadingCard />
  const stages = policy.stage_weights ?? []
  const normalize = policy.normalize_to ?? [0, 1]

  return (
    <div className="space-y-4">
      <DetailHeader title={policy.id ?? "聚合策略"} sub="" meta={[
        { label: "阶段数", value: String(stages.length) },
        { label: "归一化", value: `[${normalize.join(", ")}]` },
      ]} />

      <Card>
        <CardHeader><CardTitle className="text-sm">阶段权重</CardTitle></CardHeader>
        <CardContent>
          <div className="space-y-1">
            {stages.map((s: any, i: number) => (
              <div key={i} className="flex items-center gap-3 border-t py-2 text-sm first:border-t-0">
                <span className="w-28 shrink-0 font-mono text-xs">{s.stage_id}</span>
                {s.id && <Badge variant="outline" className="shrink-0 text-[10px]">{s.id}</Badge>}
                <span className="shrink-0 text-xs text-muted-foreground">w={s.weight}</span>
                {s.is_gate && <Badge className="shrink-0 bg-red-500/15 text-red-400 text-[10px]">GATE</Badge>}
                {s.evaluator_weights && (
                  <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-muted-foreground">
                    {Object.keys(s.evaluator_weights).join(", ")}
                  </span>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Reward 公式</CardTitle></CardHeader>
        <CardContent>
          <code className="text-sm text-emerald-400">
            Reward = (Σ stage_score × weight) / Σ weight
          </code>
          <p className="mt-2 text-xs text-muted-foreground">
            归一化到 [{normalize.join(", ")}]，门控阶段失败 → score=0（非负惩罚）。
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

// ── 5. 指标定义详情 ──

function MetricsDetail({ defs }: { defs: MetricDef[] }) {
  return (
    <div className="space-y-4">
      <DetailHeader title={`指标定义（${defs.length} 项）`} sub="" meta={[]} />
      <div className="grid gap-3 sm:grid-cols-2">
        {defs.map((d) => (
          <MetricCard key={d.id} def={d} />
        ))}
      </div>
    </div>
  )
}

function MetricCard({ def }: { def: MetricDef }) {
  const thr = def.threshold
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs text-muted-foreground">{def.id}</span>
          <Badge variant="secondary" className="text-[10px]">{def.unit ?? "—"}</Badge>
        </div>
        <div className="mt-1 text-sm font-medium">{def.name ?? def.id}</div>
        <div className="mt-2 rounded bg-muted/50 px-2 py-1 font-mono text-xs text-emerald-400">
          {def.expression ?? "—"}
        </div>
        {thr != null && (
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs text-muted-foreground">阈值</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-emerald-500" style={{ width: `${thr * 100}%` }} />
            </div>
            <span className="font-mono text-xs">≥ {thr}</span>
          </div>
        )}
        {def.explain && (
          <div className="mt-3 space-y-1 border-t pt-2">
            {def.explain.rows.map((r: MetricExplainRow, i: number) => (
              <div key={i} className="text-xs">
                <span className="font-mono text-muted-foreground">{r.dt}</span>{" "}
                <span style={{
                  color: r.tone === "danger" ? "var(--destructive)"
                    : r.tone === "success" ? "var(--chart-2)"
                    : r.tone === "primary" ? "var(--text-primary)"
                    : "var(--muted-foreground)"
                }}>{r.dd}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── 共享组件 ──

function DetailHeader({ title, sub, meta }: { title: string; sub: string; meta: { label: string; value: string }[] }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">{title}</h2>
      {sub && <p className="mt-0.5 text-sm text-muted-foreground">{sub}</p>}
      {meta.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-4">
          {meta.map((m) => (
            <span key={m.label} className="text-xs text-muted-foreground">
              {m.label}: <span className="text-foreground">{m.value}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function CodeBlock({ label, content, highlightVars }: { label: string; content: string; highlightVars?: boolean }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">{label}</CardTitle></CardHeader>
      <CardContent>
        <pre className="scroll-area max-h-[400px] overflow-auto whitespace-pre-wrap rounded bg-muted/30 p-3 font-mono text-xs leading-relaxed text-muted-foreground">
          {highlightVars
            ? content.replace(/\{\{[^}]+\}\}/g, (m) => `${m}`).split("\n").map((line, i) => (
                <span key={i}>
                  {line.split("").map((part, j) =>
                    part.startsWith("{{") ? (
                      <span key={j} className="text-blue-400">{part}</span>
                    ) : (
                      <span key={j}>{part}</span>
                    ),
                  )}
                  {"\n"}
                </span>
              ))
            : content}
        </pre>
      </CardContent>
    </Card>
  )
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="py-10 text-center text-sm text-muted-foreground">加载中…</CardContent>
    </Card>
  )
}
