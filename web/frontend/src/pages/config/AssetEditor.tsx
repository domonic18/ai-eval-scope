/**
 * 统一资产编辑器（P4-2/3/4/5 升级版）。
 *
 * 按 kind 切换专用表单（RuleSetForm / PromptForm / DatasetForm）+ YAML 模式切换 +
 * 版本时间线 + 标签晋升 + 版本 diff。替代旧的纯 YAML textarea 编辑器。
 */

import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import * as yaml from "js-yaml"
import { useCrumbs } from "../../components/AppShell"
import { Page } from "../../components/shared"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/shadcn/card"
import { Badge } from "../../components/shadcn/badge"
import { Button } from "../../components/shadcn/button"
import { Input } from "../../components/shadcn/input"
import { Label } from "../../components/shadcn/label"
import { Textarea } from "../../components/shadcn/textarea"
import { toast } from "sonner"
import { api, type AssetKind, type CatalogEntry, type DatasetCatalogEntry } from "../../api/client"
import {
  ArrowUpCircle,
  Code2,
  FileText,
  GitBranch,
  GitCompare,
  Save,
  Upload,
} from "lucide-react"
import { RuleSetForm, type RuleSetData } from "./forms/RuleSetForm"
import { PromptForm, type PromptData } from "./forms/PromptForm"
import { DatasetForm, type DatasetData } from "./forms/DatasetForm"

const KIND_LABEL: Record<AssetKind, string> = {
  "rule-sets": "规则集",
  prompts: "提示词",
  datasets: "数据集",
}
const VERSION_LABELS = ["production", "staging", "latest"]
const errMsg = (e: unknown, fb: string) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb

type Mode = "form" | "yaml"

export default function AssetEditor() {
  const { id = "", kind = "rule-sets", assetId = "" } = useParams<{
    id: string
    kind: AssetKind
    assetId: string
  }>()
  const { setCrumbs } = useCrumbs()

  const [mode, setMode] = useState<Mode>("form")
  const [content, setContent] = useState<Record<string, any> | null>(null)
  const [yamlText, setYamlText] = useState("")
  const [baselineYaml, setBaselineYaml] = useState("")
  const [draftKey, setDraftKey] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [version, setVersion] = useState("1.0.0")
  const [label, setLabel] = useState("latest")
  const [busy, setBusy] = useState(false)
  const dirty = !!content && yamlText !== baselineYaml
  const [versions, setVersions] = useState<
    Array<{ version: string; labels: string[]; contentHash: string; createdAt: string }>
  >([])
  const [diffVersion, setDiffVersion] = useState<string | null>(null)
  const [diffContent, setDiffContent] = useState<string | null>(null)
  // 规则集表单按评估方式绑定包内提示词/参考数据集所需
  const [prompts, setPrompts] = useState<CatalogEntry[]>([])
  const [refDatasets, setRefDatasets] = useState<DatasetCatalogEntry[]>([])

  useEffect(() => {
    setCrumbs([
      { label: "配置中心", to: "/config" },
      { label: id, to: `/config/scenarios/${id}` },
      { label: `${KIND_LABEL[kind]} · ${assetId}` },
    ])
    setContent(null)
    setLoading(true)
    setDraftKey(`draft:${id}:${kind}:${assetId}`)
    api
      .assetContent(id, kind, assetId)
      .then((c) => {
        // 数据集 role 不在 content 内（在 DB DatasetAsset.role 列），补充默认值
        if (kind === "datasets" && !c.role) c.role = "reference"
        setContent(c)
        const y = yaml.dump(c, { sortKeys: false })
        setYamlText(y)
        setBaselineYaml(y)
      })
      .catch(() => setContent(null))
      .finally(() => setLoading(false))
    api.listAssetVersions(id, kind, assetId).then(setVersions).catch(() => setVersions([]))
    // 载入场景资产目录，供规则集表单选择提示词/参考数据集
    api
      .scenarioCatalog(id)
      .then((c) => {
        setPrompts(c.prompts)
        setRefDatasets(c.datasets.filter((d) => d.role === "reference"))
      })
      .catch(() => {})
  }, [id, kind, assetId, setCrumbs])

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
      // YAML 语法错误时不更新 content（用户继续编辑）
    }
  }

  const saveDraft = () => {
    if (!content || !draftKey) return
    localStorage.setItem(draftKey, JSON.stringify({ content, savedAt: new Date().toISOString() }))
    setBaselineYaml(yamlText)
    toast.success("草稿已保存到本地")
  }

  const publish = async () => {
    setBusy(true)
    try {
      const publishContent = content ?? {}
      const input: Parameters<typeof api.publishAsset>[2] = {
        asset_id: assetId,
        version,
        labels: label ? [label] : [],
        content: publishContent,
      }
      if (kind === "datasets") {
        input.role = (publishContent as any).role ?? "reference"
        input.backend_type = (publishContent as any).backend_type ?? "yaml_file"
      }
      await api.publishAsset(id, kind, input)
      toast.success(`已发布 ${KIND_LABEL[kind]} ${assetId}@${version}`)
      const newVersions = await api.listAssetVersions(id, kind, assetId)
      setVersions(newVersions)
      setBaselineYaml(yamlText)
    } catch (e) {
      toast.error(errMsg(e, "发布失败"))
    } finally {
      setBusy(false)
    }
  }

  const promote = async (ver: string, lbl: string) => {
    try {
      await api.promoteAssetLabels(id, kind, assetId, ver, [lbl])
      toast.success(`${ver} 已晋升为 ${lbl}`)
      setVersions(await api.listAssetVersions(id, kind, assetId))
    } catch (e) {
      toast.error(errMsg(e, "晋升失败"))
    }
  }

  const showDiff = async (ver: string) => {
    if (diffVersion === ver) {
      setDiffVersion(null)
      setDiffContent(null)
      return
    }
    try {
      const old = await api.assetContent(id, kind, assetId, ver)
      setDiffVersion(ver)
      setDiffContent(yaml.dump(old, { sortKeys: false }))
    } catch {
      toast.error("获取版本内容失败")
    }
  }

  if (loading) return <Page><div className="text-sm text-muted-foreground">加载中…</div></Page>

  return (
    <Page>
      {/* 顶部工具栏：模式切换 + 操作按钮 */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex rounded-md border">
          <button
            type="button"
            onClick={() => setMode("form")}
            className={`flex items-center gap-1 rounded-l-md px-3 py-1.5 text-sm transition-colors ${mode === "form" ? "bg-primary font-medium text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
          >
            <FileText className="size-3.5" /> 表单模式
          </button>
          <button
            type="button"
            onClick={() => setMode("yaml")}
            className={`flex items-center gap-1 rounded-r-md px-3 py-1.5 text-sm transition-colors ${mode === "yaml" ? "bg-primary font-medium text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
          >
            <Code2 className="size-3.5" /> YAML 模式
          </button>
        </div>
        <div className="flex items-center gap-2">
          {dirty && (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="size-2 rounded-full bg-warning shadow-[0_0_0_3px_var(--warning-soft)]" />
              有未保存改动
            </span>
          )}
          <Button variant="outline" size="sm" onClick={saveDraft} disabled={!dirty}>
            <Save className="mr-1 size-4" /> 保存草稿
          </Button>
          <Button size="sm" onClick={publish} disabled={busy || !version}>
            <Upload className="mr-1 size-4" /> {busy ? "发布中…" : "发布"}
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        {/* 左：编辑区 */}
        <div className="space-y-4">
          {/* 版本 diff 视图 */}
          {diffVersion && diffContent ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">版本对比：当前编辑 vs {diffVersion}</span>
                <Button size="sm" variant="ghost" onClick={() => { setDiffVersion(null); setDiffContent(null) }}>关闭对比</Button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Card>
                  <CardHeader><CardTitle className="text-xs text-muted-foreground">{diffVersion}</CardTitle></CardHeader>
                  <CardContent>
                    <pre className="max-h-[400px] overflow-auto whitespace-pre-wrap rounded bg-muted/20 p-3 font-mono text-xs text-muted-foreground">{diffContent}</pre>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-xs text-muted-foreground">当前编辑</CardTitle></CardHeader>
                  <CardContent>
                    <pre className="max-h-[400px] overflow-auto whitespace-pre-wrap rounded bg-muted/20 p-3 font-mono text-xs text-muted-foreground">{yamlText}</pre>
                  </CardContent>
                </Card>
              </div>
            </div>
          ) : (
            <>
              {/* 表单模式 */}
              {mode === "form" && content && kind === "rule-sets" && (
                <RuleSetForm
                  data={content as RuleSetData}
                  onChange={updateContent}
                  prompts={prompts}
                  datasets={refDatasets}
                />
              )}
              {mode === "form" && content && kind === "prompts" && (
                <PromptForm data={content as PromptData} onChange={updateContent} />
              )}
              {mode === "form" && content && kind === "datasets" && (
                <DatasetForm data={content as DatasetData} onChange={updateContent} />
              )}

              {/* YAML 模式 */}
              {mode === "yaml" && (
                <Card>
                  <CardHeader><CardTitle className="text-sm">YAML 编辑</CardTitle></CardHeader>
                  <CardContent>
                    <Textarea
                      className="min-h-[500px] font-mono text-xs leading-relaxed"
                      value={yamlText}
                      onChange={(e) => onYamlChange(e.target.value)}
                    />
                  </CardContent>
                </Card>
              )}
            </>
          )}

        </div>

        {/* 右：版本时间线 */}
        <Card className="h-fit">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-1.5 text-sm"><GitBranch className="size-4" /> 版本时间线</CardTitle>
            <Button size="sm" variant="outline" onClick={publish} disabled={busy || !version}>
              <Upload className="mr-1 size-3" /> 发布新版本
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-end gap-2 border-b border-border pb-3">
              <div className="flex-1">
                <Label className="text-[11px] text-muted-foreground">版本号</Label>
                <Input
                  value={version}
                  onChange={(e) => setVersion(e.target.value)}
                  placeholder="1.0.0"
                  className="mt-1 h-8 font-mono text-xs"
                />
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">标签</Label>
                <select
                  className="mt-1 h-8 rounded-md border bg-background px-2 text-xs"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                >
                  <option value="">(无)</option>
                  {VERSION_LABELS.map((l) => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
              </div>
            </div>
            {versions.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无历史版本</p>
            ) : (
              versions.map((v) => (
                <div key={v.version} className="rounded-md border border-border p-2.5">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-medium">{v.version}</span>
                    <div className="flex gap-1">
                      {v.labels.map((l) => (
                        <Badge key={l} variant={l === "production" ? "default" : "secondary"} className="text-[10px]">{l}</Badge>
                      ))}
                    </div>
                  </div>
                  <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">{v.contentHash}</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    <Button size="sm" variant="outline" className="h-6 px-2 text-[10px]" onClick={() => showDiff(v.version)}>
                      <GitCompare className="mr-1 size-3" /> 对比
                    </Button>
                    {VERSION_LABELS.filter((l) => !v.labels.includes(l)).map((l) => (
                      <Button key={l} size="sm" variant="outline" className="h-6 px-2 text-[10px]" onClick={() => promote(v.version, l)}>
                        <ArrowUpCircle className="mr-1 size-3" /> {l}
                      </Button>
                    ))}
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
