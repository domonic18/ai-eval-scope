/**
 * 场景包编辑器 — 一个页面管理包内所有资产。
 *
 * 左侧资产树（规则集/提示词/参考数据/聚合策略/指标定义）+ 右侧编辑面板。
 * 点击树节点切换右侧编辑器（RuleSetForm/PromptForm/DatasetForm/只读详情）+ 版本时间线。
 */

import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import * as yaml from "js-yaml"
import { useCrumbs } from "../../components/AppShell"
import { Page, PageHead, TierChip } from "../../components/shared"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/shadcn/card"
import { Badge } from "../../components/shadcn/badge"
import { Button } from "../../components/shadcn/button"
import { Input } from "../../components/shadcn/input"
import { Label } from "../../components/shadcn/label"
import { Textarea } from "../../components/shadcn/textarea"
import { toast } from "sonner"
import { api, type AssetKind, type CatalogEntry } from "../../api/client"
import type { MetricDef, MetricExplainRow } from "../../types"
import {
  ArrowUpCircle,
  BookOpen,
  ChevronRight,
  Code2,
  Database,
  FileText,
  Gauge,
  GitBranch,
  GitCompare,
  Layers,
  Save,
} from "lucide-react"
import { RuleSetForm, type RuleSetData } from "./forms/RuleSetForm"
import { PromptForm, type PromptData } from "./forms/PromptForm"
import { DatasetForm, type DatasetData } from "./forms/DatasetForm"

type Selection =
  | { type: "rule-set"; assetId: string }
  | { type: "prompt"; assetId: string }
  | { type: "dataset"; assetId: string }
  | { type: "policy" }
  | { type: "metrics" }

const VERSION_LABELS = ["production", "staging", "latest"]
const errMsg = (e: unknown, fb: string) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb

export default function PackageEditor() {
  const { id = "" } = useParams<{ id: string }>()
  const { setCrumbs } = useCrumbs()
  const [catalog, setCatalog] = useState<{
    rule_sets: CatalogEntry[]
    prompts: CatalogEntry[]
    datasets: CatalogEntry[]
  } | null>(null)
  const [sel, setSel] = useState<Selection | null>(null)
  const [content, setContent] = useState<Record<string, any> | null>(null)
  const [yamlText, setYamlText] = useState("")
  const [mode, setMode] = useState<"form" | "yaml">("form")
  const [loading, setLoading] = useState(false)
  const [version, setVersion] = useState("1.0.0")
  const [label, setLabel] = useState("latest")
  const [busy, setBusy] = useState(false)
  const [versions, setVersions] = useState<
    Array<{ version: string; labels: string[]; contentHash: string; createdAt: string }>
  >([])
  const [diffVersion, setDiffVersion] = useState<string | null>(null)
  const [diffContent, setDiffContent] = useState<string | null>(null)

  useEffect(() => {
    setCrumbs([
      { label: "配置中心", to: "/config" },
      { label: id, to: `/config/scenarios/${id}` },
      { label: "包编辑器" },
    ])
    api
      .scenarioCatalog(id)
      .then((c) => {
        setCatalog(c)
        if (c.rule_sets.length) selectAsset({ type: "rule-set", assetId: c.rule_sets[0].asset_id })
      })
      .catch(() => {})
  }, [id, setCrumbs])

  const selectAsset = (s: Selection) => {
    setSel(s)
    setContent(null)
    setDiffVersion(null)
    setDiffContent(null)
    setLoading(true)
    if (s.type === "policy" || s.type === "metrics") {
      setLoading(false)
      return
    }
    const kind = s.type === "rule-set" ? "rule-sets" : s.type === "prompt" ? "prompts" : "datasets"
    api
      .assetContent(id, kind as AssetKind, s.assetId)
      .then((c) => {
        if (s.type === "dataset" && !c.role) c.role = "reference"
        setContent(c)
        setYamlText(yaml.dump(c, { sortKeys: false }))
        const ver = (catalog as any)?.[s.type === "rule-set" ? "rule_sets" : s.type === "prompt" ? "prompts" : "datasets"]?.find(
          (e: any) => e.asset_id === s.assetId,
        )?.version
        if (ver) setVersion(ver)
        api.listAssetVersions(id, kind as AssetKind, s.assetId).then(setVersions).catch(() => setVersions([]))
      })
      .catch(() => setContent(null))
      .finally(() => setLoading(false))
  }

  const updateContent = (d: Record<string, any>) => {
    setContent(d)
    setYamlText(yaml.dump(d, { sortKeys: false }))
  }
  const onYamlChange = (text: string) => {
    setYamlText(text)
    try {
      const parsed = yaml.load(text)
      if (parsed && typeof parsed === "object") setContent(parsed as Record<string, any>)
    } catch {
      /* YAML 语法错误时继续编辑 */
    }
  }

  const publish = async () => {
    if (!sel || sel.type === "policy" || sel.type === "metrics") return
    setBusy(true)
    try {
      const kind = sel.type === "rule-set" ? "rule-sets" : sel.type === "prompt" ? "prompts" : "datasets"
      const input: Parameters<typeof api.publishAsset>[2] = {
        asset_id: sel.assetId,
        version,
        labels: label ? [label] : [],
        content: content ?? {},
      }
      if (sel.type === "dataset") {
        input.role = (content as any)?.role ?? "reference"
        input.backend_type = (content as any)?.backend_type ?? "yaml_file"
      }
      await api.publishAsset(id, kind as AssetKind, input)
      toast.success(`已发布 ${sel.assetId}@${version}`)
      setVersions(await api.listAssetVersions(id, kind as AssetKind, sel.assetId))
    } catch (e) {
      toast.error(errMsg(e, "发布失败"))
    } finally {
      setBusy(false)
    }
  }

  const promote = async (ver: string, lbl: string) => {
    if (!sel || sel.type === "policy" || sel.type === "metrics") return
    try {
      const kind = sel.type === "rule-set" ? "rule-sets" : sel.type === "prompt" ? "prompts" : "datasets"
      await api.promoteAssetLabels(id, kind as AssetKind, sel.assetId, ver, [lbl])
      toast.success(`${ver} 已晋升为 ${lbl}`)
      setVersions(await api.listAssetVersions(id, kind as AssetKind, sel.assetId))
    } catch (e) {
      toast.error(errMsg(e, "晋升失败"))
    }
  }

  const showDiff = async (ver: string) => {
    if (!sel || sel.type === "policy" || sel.type === "metrics") return
    if (diffVersion === ver) {
      setDiffVersion(null)
      setDiffContent(null)
      return
    }
    try {
      const kind = sel.type === "rule-set" ? "rule-sets" : sel.type === "prompt" ? "prompts" : "datasets"
      const old = await api.assetContent(id, kind as AssetKind, sel.assetId, ver)
      setDiffVersion(ver)
      setDiffContent(yaml.dump(old, { sortKeys: false }))
    } catch {
      toast.error("获取版本内容失败")
    }
  }

  const selKind: AssetKind | null =
    sel?.type === "rule-set" ? "rule-sets" : sel?.type === "prompt" ? "prompts" : sel?.type === "dataset" ? "datasets" : null
  const canEdit = sel && sel.type !== "policy" && sel.type !== "metrics"

  return (
    <Page>
      <PageHead title="场景包编辑器" sub={`${id} 场景 · 统一编辑包内所有配置资产`} />
      <div className="grid gap-4 lg:grid-cols-[220px_1fr_280px]">
        {/* ── 左侧资产树 ── */}
        <Card className="h-fit">
          <CardContent className="space-y-4 p-3">
            <TreeSection icon={Layers} label="规则集">
              {catalog?.rule_sets.length === 0 && (
                <p className="px-2 py-1 text-[11px] text-muted-foreground/60">无规则集，先发布一个</p>
              )}
              {catalog?.rule_sets.map((r) => (
                <TreeNode key={r.asset_id} active={sel?.type === "rule-set" && sel.assetId === r.asset_id}
                  name={r.asset_id} icon={FileText} onClick={() => selectAsset({ type: "rule-set", assetId: r.asset_id })} />
              ))}
            </TreeSection>
            <TreeSection icon={BookOpen} label="提示词">
              {catalog?.prompts.length === 0 && (
                <p className="px-2 py-1 text-[11px] text-muted-foreground/60">暂无，发布规则集后在右侧添加</p>
              )}
              {catalog?.prompts.map((p) => (
                <TreeNode key={p.asset_id} active={sel?.type === "prompt" && sel.assetId === p.asset_id}
                  name={p.asset_id} icon={FileText} onClick={() => selectAsset({ type: "prompt", assetId: p.asset_id })} />
              ))}
            </TreeSection>
            <TreeSection icon={Database} label="参考数据">
              {catalog?.datasets.length === 0 && (
                <p className="px-2 py-1 text-[11px] text-muted-foreground/60">暂无，可选</p>
              )}
              {catalog?.datasets.map((d) => (
                <TreeNode key={d.asset_id} active={sel?.type === "dataset" && sel.assetId === d.asset_id}
                  name={d.asset_id} icon={Database} onClick={() => selectAsset({ type: "dataset", assetId: d.asset_id })} />
              ))}
            </TreeSection>
            <TreeSection icon={Gauge} label="策略">
              <TreeNode active={sel?.type === "policy"} name="聚合策略" icon={Gauge} onClick={() => selectAsset({ type: "policy" })} />
              <TreeNode active={sel?.type === "metrics"} name="指标定义" icon={Layers} onClick={() => selectAsset({ type: "metrics" })} />
            </TreeSection>
          </CardContent>
        </Card>

        {/* ── 中间编辑面板 ── */}
        <div className="space-y-3">
          {/* 面包屑 + 模式切换 */}
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              {sel?.type === "rule-set" && `规则集 · ${sel.assetId}`}
              {sel?.type === "prompt" && `提示词 · ${sel.assetId}`}
              {sel?.type === "dataset" && `数据集 · ${sel.assetId}`}
              {sel?.type === "policy" && "聚合策略"}
              {sel?.type === "metrics" && "指标定义"}
            </span>
            {canEdit && (
              <div className="flex gap-2">
                <div className="flex rounded-md border">
                  <button onClick={() => setMode("form")} className={`rounded-l-md px-3 py-1 text-xs ${mode === "form" ? "bg-accent font-medium" : "text-muted-foreground"}`}>
                    <FileText className="mr-1 inline size-3" />表单
                  </button>
                  <button onClick={() => setMode("yaml")} className={`rounded-r-md px-3 py-1 text-xs ${mode === "yaml" ? "bg-accent font-medium" : "text-muted-foreground"}`}>
                    <Code2 className="mr-1 inline size-3" />YAML
                  </button>
                </div>
                <Button size="sm" onClick={publish} disabled={busy}>
                  <Save className="mr-1 size-3" />{busy ? "发布中…" : "发布"}
                </Button>
              </div>
            )}
          </div>

          {/* 版本 diff */}
          {diffVersion && diffContent ? (
            <div className="grid gap-2 sm:grid-cols-2">
              <Card><CardHeader><CardTitle className="text-xs text-muted-foreground">{diffVersion}</CardTitle></CardHeader>
                <CardContent><pre className="max-h-[400px] overflow-auto whitespace-pre-wrap rounded bg-muted/20 p-2 font-mono text-xs text-muted-foreground">{diffContent}</pre></CardContent></Card>
              <Card><CardHeader><CardTitle className="text-xs text-muted-foreground">当前编辑</CardTitle></CardHeader>
                <CardContent><pre className="max-h-[400px] overflow-auto whitespace-pre-wrap rounded bg-muted/20 p-2 font-mono text-xs text-muted-foreground">{yamlText}</pre></CardContent></Card>
            </div>
          ) : loading ? (
            <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">加载中…</CardContent></Card>
          ) : diffVersion ? null : (
            <>
              {/* 表单模式 */}
              {canEdit && mode === "form" && content && sel?.type === "rule-set" && (
                <RuleSetForm data={content as RuleSetData} onChange={updateContent} />
              )}
              {canEdit && mode === "form" && content && sel?.type === "prompt" && (
                <PromptForm data={content as PromptData} onChange={updateContent} />
              )}
              {canEdit && mode === "form" && content && sel?.type === "dataset" && (
                <DatasetForm data={content as DatasetData} onChange={updateContent} />
              )}
              {/* YAML 模式 */}
              {canEdit && mode === "yaml" && (
                <Card><CardContent><Textarea className="min-h-[500px] font-mono text-xs leading-relaxed" value={yamlText} onChange={(e) => onYamlChange(e.target.value)} /></CardContent></Card>
              )}
              {/* 聚合策略（只读） */}
              {sel?.type === "policy" && <PolicyReadonly scenarioId={id} />}
              {/* 指标定义（只读） */}
              {sel?.type === "metrics" && <MetricsReadonly scenarioId={id} />}
            </>
          )}

          {/* 发布设置 */}
          {canEdit && (
            <Card>
              <CardContent className="flex items-end gap-3 p-4">
                <div><Label>版本号</Label><Input value={version} onChange={(e) => setVersion(e.target.value)} className="font-mono" /></div>
                <div><Label>标签</Label>
                  <select className="rounded-md border bg-background px-3 py-2 text-sm" value={label} onChange={(e) => setLabel(e.target.value)}>
                    <option value="">(无)</option>
                    {VERSION_LABELS.map((l) => <option key={l} value={l}>{l}</option>)}
                  </select>
                </div>
                <Button onClick={publish} disabled={busy || !version}><Save className="mr-1 size-4" />{busy ? "发布中…" : "发布"}</Button>
              </CardContent>
            </Card>
          )}
        </div>

        {/* ── 右侧版本时间线 ── */}
        {canEdit && selKind && (
          <Card className="h-fit">
            <CardHeader className="pb-2"><CardTitle className="flex items-center gap-1.5 text-sm"><GitBranch className="size-4" />版本时间线</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {versions.length === 0 ? (
                <p className="text-xs text-muted-foreground">暂无历史版本</p>
              ) : versions.map((v) => (
                <div key={v.version} className="rounded-md border p-2">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-medium">{v.version}</span>
                    <div className="flex gap-0.5">
                      {v.labels.map((l) => <Badge key={l} variant={l === "production" ? "default" : "secondary"} className="text-[9px]">{l}</Badge>)}
                    </div>
                  </div>
                  <p className="mt-0.5 truncate font-mono text-[9px] text-muted-foreground">{v.contentHash}</p>
                  <div className="mt-1 flex flex-wrap gap-0.5">
                    <Button size="sm" variant="outline" className="h-5 px-1.5 text-[9px]" onClick={() => showDiff(v.version)}>
                      <GitCompare className="mr-0.5 size-2.5" />对比
                    </Button>
                    {VERSION_LABELS.filter((l) => !v.labels.includes(l)).map((l) => (
                      <Button key={l} size="sm" variant="outline" className="h-5 px-1.5 text-[9px]" onClick={() => promote(v.version, l)}>
                        <ArrowUpCircle className="mr-0.5 size-2.5" />{l}
                      </Button>
                    ))}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>
    </Page>
  )
}

// ── 左侧树组件 ──
function TreeSection({ icon: Icon, label, children }: { icon: any; label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1 px-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"><Icon className="size-3" />{label}</div>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}
function TreeNode({ active, name, icon: Icon, onClick }: { active: boolean; name: string; icon: any; onClick: () => void }) {
  return (
    <button onClick={onClick} className={`flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left text-xs transition-colors ${active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"}`}>
      <Icon className="size-3 shrink-0 opacity-60" /><span className="flex-1 truncate font-mono">{name}</span>
      {active && <ChevronRight className="size-3 shrink-0" />}
    </button>
  )
}

// ── 聚合策略只读 ──
function PolicyReadonly({ scenarioId }: { scenarioId: string }) {
  const [policy, setPolicy] = useState<Record<string, any> | null>(null)
  useEffect(() => { api.scenarioAggregationPolicy(scenarioId).then(setPolicy).catch(() => setPolicy(null)) }, [scenarioId])
  if (!policy) return <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">加载中…</CardContent></Card>
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">{policy.id ?? "聚合策略"}</CardTitle></CardHeader>
      <CardContent className="space-y-1">
        {(policy.stage_weights ?? []).map((s: any, i: number) => (
          <div key={i} className="flex items-center gap-2 border-t py-1.5 text-xs first:border-t-0">
            <span className="w-24 font-mono">{s.stage_id}</span>
            {s.id && <Badge variant="outline" className="text-[9px]">{s.id}</Badge>}
            <span className="text-muted-foreground">w={s.weight}</span>
            {s.is_gate && <Badge className="bg-red-500/15 text-red-400 text-[9px]">GATE</Badge>}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

// ── 指标定义只读 ──
function MetricsReadonly({ scenarioId }: { scenarioId: string }) {
  const [defs, setDefs] = useState<MetricDef[]>([])
  useEffect(() => { api.scenarioDefaults(scenarioId).then(setDefs).catch(() => setDefs([])) }, [scenarioId])
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {defs.map((d) => <MetricMiniCard key={d.id} def={d} />)}
    </div>
  )
}
function MetricMiniCard({ def }: { def: MetricDef }) {
  return (
    <Card><CardContent className="p-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-muted-foreground">{def.id}</span>
        <Badge variant="secondary" className="text-[9px]">{def.unit ?? "—"}</Badge>
      </div>
      <div className="mt-0.5 text-sm font-medium">{def.name ?? def.id}</div>
      <div className="mt-1 rounded bg-muted/50 px-2 py-0.5 font-mono text-[10px] text-emerald-400">{def.expression ?? "—"}</div>
      {def.threshold != null && <div className="mt-1 text-[10px] text-muted-foreground">阈值 ≥ {def.threshold}</div>}
    </CardContent></Card>
  )
}
