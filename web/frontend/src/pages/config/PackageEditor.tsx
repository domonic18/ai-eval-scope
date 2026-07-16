/**
 * 场景包编辑器 — 一个页面管理包内所有资产。
 *
 * 左资产树 + 中编辑面板（表单/YAML）+ 右版本时间线（sticky + 草稿卡）。
 * 顶栏：dirty 指示 + 保存草稿(localStorage) + 发布(Modal 多选标签)。
 * 规则集时右侧附带「配置完整度」面板（前端派生）。
 */

import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import * as yaml from "js-yaml"
import { useCrumbs } from "../../components/AppShell"
import { Page, PageHead } from "../../components/shared"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/shadcn/card"
import { Button } from "../../components/shadcn/button"
import { Input } from "../../components/shadcn/input"
import { Textarea } from "../../components/shadcn/textarea"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../components/shadcn/dialog"
import { toast } from "sonner"
import { api, type AssetKind, type CatalogEntry, type DatasetCatalogEntry } from "../../api/client"
import { BookOpen, ChevronRight, Database, FileText, Gauge, GitBranch, Layers, Plus, Save, Upload } from "lucide-react"
import { RuleSetForm, type RuleSetData } from "./forms/RuleSetForm"
import { PromptForm, type PromptData } from "./forms/PromptForm"
import { DatasetForm, type DatasetData } from "./forms/DatasetForm"
import { createEmptyPrompt, createEmptyDataset } from "./forms/defaults"
import { MetricDefsEditor } from "./forms/MetricDefsEditor"
import { AggregationPolicyEditor } from "./forms/AggregationPolicyEditor"
import { CompletenessPanel } from "./forms/CompletenessPanel"
import { FormYamlToggle } from "./forms/Field"

type Selection =
  | { type: "rule-set"; assetId: string }
  | { type: "prompt"; assetId: string }
  | { type: "dataset"; assetId: string }
  | { type: "policy" }
  | { type: "metrics" }

const VERSION_LABELS = ["production", "staging", "latest"]
const errMsg = (e: unknown, fb: string) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb

/** 相对时间 + 日期，对齐原型 .vc-time */
function relTime(iso: string): string {
  const d = new Date(iso)
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  const ago = days > 30 ? `${Math.floor(days / 30)}个月前` : days > 0 ? `${days}天前` : "今天"
  return `${ago} · ${d.toLocaleDateString("zh-CN")}`
}

export default function PackageEditor() {
  const { id = "" } = useParams<{ id: string }>()
  const { setCrumbs } = useCrumbs()
  const [catalog, setCatalog] = useState<{
    rule_sets: CatalogEntry[]
    prompts: CatalogEntry[]
    datasets: DatasetCatalogEntry[]
  } | null>(null)
  const [sel, setSel] = useState<Selection | null>(null)
  const [content, setContent] = useState<Record<string, any> | null>(null)
  const [yamlText, setYamlText] = useState("")
  const [baselineYaml, setBaselineYaml] = useState("")
  const [mode, setMode] = useState<"form" | "yaml">("form")
  const [loading, setLoading] = useState(false)
  const [version, setVersion] = useState("1.0.0")
  const [busy, setBusy] = useState(false)
  const [versions, setVersions] = useState<
    Array<{ version: string; labels: string[]; contentHash: string; createdAt: string }>
  >([])
  const [diffVersion, setDiffVersion] = useState<string | null>(null)
  const [diffContent, setDiffContent] = useState<string | null>(null)
  // 发布 Modal（多选标签）
  const [pubOpen, setPubOpen] = useState(false)
  const [pubLabels, setPubLabels] = useState<string[]>([])
  // 草稿恢复
  const [draftRestore, setDraftRestore] = useState<Record<string, any> | null>(null)
  // 完整度数据
  const [metricCount, setMetricCount] = useState(0)
  const [hasPolicy, setHasPolicy] = useState(false)

  const dirty = !!sel && sel.type !== "policy" && sel.type !== "metrics" && yamlText !== baselineYaml

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
    // 完整度：场景默认指标 + 聚合策略
    api.scenarioDefaults(id).then((m) => setMetricCount(m.length)).catch(() => {})
    api.scenarioAggregationPolicy(id).then((p) => setHasPolicy(p != null)).catch(() => {})
  }, [id, setCrumbs])

  const draftKey = (s: Selection | null): string | null => {
    if (!s || s.type === "policy" || s.type === "metrics") return null
    const kind = s.type === "rule-set" ? "rule-sets" : s.type === "prompt" ? "prompts" : "datasets"
    return `draft:${id}:${kind}:${s.assetId}`
  }

  // 新建空白资产（提示词/数据集）
  const newAsset = (kind: AssetKind) => {
    const assetId = kind === "prompts" ? `prompt_${Date.now().toString(36).slice(-4)}` : `dataset_${Date.now().toString(36).slice(-4)}`
    const emptyContent = kind === "prompts" ? createEmptyPrompt(assetId) : createEmptyDataset()
    setContent(emptyContent)
    const y = yaml.dump(emptyContent, { sortKeys: false })
    setYamlText(y)
    setBaselineYaml(y)
    setVersion("0.1.0")
    setVersions([])
    setSel(kind === "prompts" ? { type: "prompt", assetId } : { type: "dataset", assetId })
    setLoading(false)
    setDiffVersion(null)
    setDiffContent(null)
    setDraftRestore(null)
  }

  const selectAsset = (s: Selection) => {
    setSel(s)
    setContent(null)
    setDiffVersion(null)
    setDiffContent(null)
    setDraftRestore(null)
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
        const y = yaml.dump(c, { sortKeys: false })
        setYamlText(y)
        setBaselineYaml(y)
        const ver = (catalog as any)?.[s.type === "rule-set" ? "rule_sets" : s.type === "prompt" ? "prompts" : "datasets"]?.find(
          (e: any) => e.asset_id === s.assetId,
        )?.version
        if (ver) setVersion(ver)
        api.listAssetVersions(id, kind as AssetKind, s.assetId).then(setVersions).catch(() => setVersions([]))
        // 检测本地草稿
        try {
          const raw = localStorage.getItem(`draft:${id}:${kind}:${s.assetId}`)
          if (raw) setDraftRestore((JSON.parse(raw).content as Record<string, any>) ?? null)
        } catch {
          /* ignore */
        }
      })
      .catch(() => setContent(null))
      .finally(() => setLoading(false))
  }

  const onJumpAsset = (type: "prompt" | "dataset", assetId: string) =>
    selectAsset({ type, assetId })

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

  const saveDraft = () => {
    const k = draftKey(sel)
    if (!k || !content) return
    localStorage.setItem(k, JSON.stringify({ content, savedAt: new Date().toISOString() }))
    setBaselineYaml(yamlText)
    toast.success("草稿已保存到本地")
  }
  const restoreDraft = () => {
    if (!draftRestore) return
    setContent(draftRestore)
    setYamlText(yaml.dump(draftRestore, { sortKeys: false }))
    setDraftRestore(null)
    toast.info("已恢复本地草稿")
  }

  const publish = async () => {
    if (!sel || sel.type === "policy" || sel.type === "metrics") return
    setBusy(true)
    try {
      const kind = sel.type === "rule-set" ? "rule-sets" : sel.type === "prompt" ? "prompts" : "datasets"
      const input: Parameters<typeof api.publishAsset>[2] = {
        asset_id: sel.assetId,
        version,
        labels: pubLabels,
        content: content ?? {},
      }
      if (sel.type === "dataset") {
        input.role = (content as any)?.role ?? "reference"
        input.backend_type = (content as any)?.backend_type ?? "yaml_file"
      }
      await api.publishAsset(id, kind as AssetKind, input)
      toast.success(`已发布 ${sel.assetId}@${version}`)
      setVersions(await api.listAssetVersions(id, kind as AssetKind, sel.assetId))
      // 发布后清理本地草稿 + 重置 baseline（dirty 归零）
      const k = draftKey(sel)
      if (k) localStorage.removeItem(k)
      setBaselineYaml(yamlText)
      setPubLabels([])
      setPubOpen(false)
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
  const assetLabel =
    sel?.type === "rule-set"
      ? `规则集 · ${sel.assetId}`
      : sel?.type === "prompt"
        ? `提示词 · ${sel.assetId}`
        : sel?.type === "dataset"
          ? `数据集 · ${sel.assetId}`
          : sel?.type === "policy"
            ? "聚合策略"
            : sel?.type === "metrics"
              ? "指标定义"
              : ""

  return (
    <Page>
      <PageHead title="场景包编辑器" sub={`${id} 场景 · 统一编辑包内所有配置资产`} />

      {/* 子顶栏：资产名 + dirty + 保存草稿 + 发布 */}
      {canEdit && (
        <div className="mb-4 flex items-center justify-between rounded-md border border-border bg-card px-4 py-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium">{assetLabel}</span>
            {dirty && (
              <>
                <span title="有未保存改动" className="size-[7px] rounded-full bg-warning shadow-[0_0_0_3px_var(--warning-soft)]" />
                <span className="text-[11px] text-warning">有未保存改动</span>
              </>
            )}
            {draftRestore && (
              <button onClick={restoreDraft} className="text-[11px] text-primary hover:underline">
                恢复本地草稿
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={saveDraft}>
              <Save className="mr-1 size-3" />保存草稿
            </Button>
            <Button size="sm" onClick={() => setPubOpen(true)}>
              <Upload className="mr-1 size-3" />发布
            </Button>
          </div>
        </div>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[220px_1fr_360px]">
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
                <p className="px-2 py-1 text-[11px] text-muted-foreground/60">暂无提示词</p>
              )}
              {catalog?.prompts.map((p) => (
                <TreeNode key={p.asset_id} active={sel?.type === "prompt" && sel.assetId === p.asset_id}
                  name={p.asset_id} icon={FileText} onClick={() => selectAsset({ type: "prompt", assetId: p.asset_id })} />
              ))}
              <button onClick={() => newAsset("prompts")} className="mt-1 flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[11px] text-primary/80 transition-colors hover:bg-accent/50">
                <Plus className="size-3" /> 新建提示词
              </button>
            </TreeSection>
            <TreeSection icon={Database} label="参考数据">
              {catalog?.datasets.length === 0 && (
                <p className="px-2 py-1 text-[11px] text-muted-foreground/60">暂无数据集</p>
              )}
              {catalog?.datasets.map((d) => (
                <TreeNode key={d.asset_id} active={sel?.type === "dataset" && sel.assetId === d.asset_id}
                  name={d.asset_id} icon={Database} onClick={() => selectAsset({ type: "dataset", assetId: d.asset_id })} />
              ))}
              <button onClick={() => newAsset("datasets")} className="mt-1 flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[11px] text-primary/80 transition-colors hover:bg-accent/50">
                <Plus className="size-3" /> 新建数据集
              </button>
            </TreeSection>
            <TreeSection icon={Gauge} label="策略">
              <TreeNode active={sel?.type === "policy"} name="聚合策略" icon={Gauge} onClick={() => selectAsset({ type: "policy" })} />
              <TreeNode active={sel?.type === "metrics"} name="指标定义" icon={Layers} onClick={() => selectAsset({ type: "metrics" })} />
            </TreeSection>
          </CardContent>
        </Card>

        {/* ── 中间编辑面板 ── */}
        <div className="space-y-3">
          {/* 模式切换 */}
          {canEdit && (
            <div className="flex items-center justify-end">
              <FormYamlToggle mode={mode} onChange={setMode} />
            </div>
          )}

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
                <RuleSetForm
                  data={content as RuleSetData}
                  onChange={updateContent}
                  prompts={catalog?.prompts ?? []}
                  datasets={(catalog?.datasets ?? []).filter((d) => d.role === "reference")}
                  onNewPrompt={() => newAsset("prompts")}
                  onNewDataset={() => newAsset("datasets")}
                  onJumpAsset={onJumpAsset}
                />
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
              {/* 聚合策略 / 指标定义 */}
              {sel?.type === "policy" && <AggregationPolicyEditor scenarioId={id} />}
              {sel?.type === "metrics" && <MetricDefsEditor scenarioId={id} />}
            </>
          )}
        </div>

        {/* ── 右侧：版本时间线（sticky）+ 配置完整度 ── */}
        {canEdit && selKind && (
          <Card className="h-fit lg:sticky lg:top-[72px]">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-1.5 text-sm"><GitBranch className="size-4" />版本时间线</CardTitle>
              <Button size="sm" variant="outline" onClick={() => setPubOpen(true)}>
                <Plus className="mr-1 size-3" />发布新版本
              </Button>
            </CardHeader>
            <CardContent>
              <div className="max-h-[calc(100vh-260px)] space-y-2 overflow-y-auto pr-1">
                {/* 当前草稿卡 */}
                {content && (
                  <div className="rounded-md border border-primary/40 bg-gradient-to-b from-primary/10 to-transparent p-2 ring-1 ring-primary/20">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs font-medium">{version || "草稿"}</span>
                      <span className="rounded-sm bg-warning/15 px-1.5 py-px text-[9px] font-semibold text-warning">编辑中</span>
                    </div>
                    <p className="mt-0.5 text-[10px] text-muted-foreground">{dirty ? "有未保存改动" : "已与已发布一致"}</p>
                  </div>
                )}
                {/* 已发布版本 */}
                {versions.length === 0 && !content ? (
                  <p className="text-xs text-muted-foreground">暂无历史版本</p>
                ) : (
                  versions.map((v) => (
                    <div key={v.version} className="rounded-md border border-border p-2 transition-colors hover:border-primary/30">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs font-medium">{v.version}</span>
                        <div className="flex gap-0.5">
                          {v.labels.map((l) => (
                            <span key={l} className={`rounded-sm px-1.5 py-px font-mono text-[9px] font-semibold ${l === "production" ? "bg-success/15 text-success" : l === "staging" ? "bg-warning/15 text-warning" : "bg-info/15 text-info"}`}>
                              {l}
                            </span>
                          ))}
                        </div>
                      </div>
                      <p className="mt-0.5 truncate font-mono text-[9px] text-muted-foreground">{v.contentHash}</p>
                      <p className="mt-0.5 text-[9px] text-muted-foreground">{relTime(v.createdAt)}</p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <button onClick={() => showDiff(v.version)} className="rounded-sm px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-accent hover:text-foreground">对比</button>
                        {VERSION_LABELS.filter((l) => !v.labels.includes(l)).map((l) => (
                          <button key={l} onClick={() => promote(v.version, l)} className="rounded-sm px-1.5 py-0.5 text-[10px] text-primary hover:bg-primary/10">晋升{l}</button>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* 配置完整度（仅规则集） */}
              {sel?.type === "rule-set" && content && (
                <CompletenessPanel data={content as RuleSetData} metricCount={metricCount} hasPolicy={hasPolicy} />
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {/* 发布 Modal */}
      <Dialog open={pubOpen} onOpenChange={setPubOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>发布新版本</DialogTitle>
            <DialogDescription>
              发布后生成不可变版本；同一标签仅绑定一个版本，发布后会自动从旧版本解绑。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-1">
            <div>
              <label className="text-[11px] text-muted-foreground">版本号（语义化，如 1.0.0）</label>
              <Input className="mt-1 font-mono" value={version} onChange={(e) => setVersion(e.target.value)} placeholder="1.0.0" />
            </div>
            <div>
              <label className="text-[11px] text-muted-foreground">标签（可多选）</label>
              <div className="mt-1.5 flex gap-2">
                {VERSION_LABELS.map((l) => {
                  const on = pubLabels.includes(l)
                  return (
                    <button
                      key={l}
                      type="button"
                      onClick={() => setPubLabels((prev) => (prev.includes(l) ? prev.filter((x) => x !== l) : [...prev, l]))}
                      className={`rounded-md border px-3 py-1 text-xs transition-colors ${on ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:text-foreground"}`}
                    >
                      {l}
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPubOpen(false)}>取消</Button>
            <Button onClick={publish} disabled={busy || !version}>{busy ? "发布中…" : "发布"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
    <button onClick={onClick} className={`flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left text-xs transition-colors ${active ? "bg-primary/15 font-medium text-primary" : "text-muted-foreground hover:bg-accent/50"}`}>
      <Icon className="size-3 shrink-0 opacity-60" /><span className="flex-1 truncate font-mono">{name}</span>
      {active && <ChevronRight className="size-3 shrink-0" />}
    </button>
  )
}
