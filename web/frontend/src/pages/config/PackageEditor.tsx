/**
 * 场景包统一编辑器（docs/arch/13配置管理设计.md）。
 *
 * 唯一编辑器入口：左资产树 + 中编辑区（Tab + 表单/YAML）+ 右版本时间线。
 * 选中资产编码进 URL `?select=<kind>:<assetId>`；旧路由 /:kind/:assetId 重定向至此。
 * 跨资产引用跳转 = 树内定位/开 Tab（不打断当前编辑）；新建资产为本地草稿，发布时校验引用。
 */

import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import * as yaml from "js-yaml"
import { useCrumbs } from "../../context/navigation"
import { Page, PageHead } from "../../components/shared"
import { Card, CardContent } from "../../components/shadcn/card"
import { Textarea } from "../../components/shadcn/textarea"
import { Button } from "../../components/shadcn/button"
import { api } from "../../api/client"
import { RuleSetForm, type RuleSetData } from "./forms/RuleSetForm"
import { PromptForm, type PromptData } from "./forms/PromptForm"
import { DatasetForm, type DatasetData } from "./forms/DatasetForm"
import { MetricDefsEditor } from "./forms/MetricDefsEditor"
import { AggregationPolicyEditor } from "./forms/AggregationPolicyEditor"
import { CompletenessPanel } from "./forms/CompletenessPanel"
import { FormYamlToggle } from "./forms/Field"
import { AssetTree } from "./editor/AssetTree"
import { EditorTabs } from "./editor/EditorTabs"
import { VersionTimeline } from "./editor/VersionTimeline"
import { useEditorStore, type Dict } from "./editor/useEditorStore"
import { canEditConfig } from "../../store/auth"
import type { MetricDef } from "../../types"
import { parseSelection } from "./editor/types"

export default function PackageEditor() {
  const { id = "" } = useParams<{ id: string }>()
  const { setCrumbs } = useCrumbs()
  const store = useEditorStore(id)
  const {
    selected,
    select,
    catalog,
    doc,
    docs,
    tabs,
    closeTab,
    updateDoc,
    dirtyOf,
    currentYaml,
    restoreDraft,
    discardDraft,
    createAsset,
    createAndBindPrompt,
    missingRefs,
    publish,
    busy,
    promote,
    diff,
    showDiff,
    setNextVersion,
  } = store

  const canEdit = canEditConfig()
  const [mode, setMode] = useState<"form" | "yaml">("form")
  const [metricCount, setMetricCount] = useState(0)
  const [hasPolicy, setHasPolicy] = useState(false)

  useEffect(() => {
    setCrumbs([
      { label: "配置中心", to: "/config" },
      { label: id, to: `/config/scenarios/${id}` },
      { label: "包编辑器" },
    ])
    api.scenarioDefaults(id).then((m) => setMetricCount(m.length)).catch(() => {})
    api.scenarioAggregationPolicy(id).then((p) => setHasPolicy(p != null)).catch(() => {})
  }, [id, setCrumbs])

  const parsed = selected ? parseSelection(selected) : null
  const isSpecial = selected === "policy" || selected === "metrics"

  const onYamlChange = (text: string) => {
    if (!selected) return
    try {
      const parsedYaml = yaml.load(text)
      if (parsedYaml && typeof parsedYaml === "object") updateDoc(selected, parsedYaml as Record<string, unknown>)
    } catch {
      /* YAML 语法错误时继续编辑 */
    }
  }

  const jumpAsset = (type: "prompt" | "dataset", assetId: string) =>
    select(`${type === "prompt" ? "prompts" : "datasets"}:${assetId}`)

  const refs = selected ? missingRefs(selected) : { prompts: [], datasets: [], unpublished: [] }

  return (
    <Page>
      <PageHead title="场景包编辑器" sub={`${id} 场景 · 统一编辑包内所有配置资产`} />

      <div className="grid items-start gap-5 lg:grid-cols-[220px_1fr_360px]">
        {/* ── 左侧资产树 ── */}
        <Card className="h-fit">
          <CardContent className="p-3">
            <AssetTree
              catalog={catalog}
              docs={docs}
              selected={selected}
              dirtyOf={dirtyOf}
              onSelect={select}
              onCreate={createAsset}
              canEdit={canEdit}
            />
          </CardContent>
        </Card>

        {/* ── 中间编辑面板 ── */}
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <EditorTabs tabs={tabs} docs={docs} selected={selected} dirtyOf={dirtyOf} onSelect={select} onClose={closeTab} />
            {parsed && <FormYamlToggle mode={mode} onChange={setMode} />}
          </div>

          {/* 草稿恢复横幅（显式确认，绝不静默覆盖） */}
          {canEdit && parsed && doc?.pendingDraft && (
            <div className="flex items-center justify-between rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
              <span className="text-warning">检测到该资产的本地草稿（未发布）。</span>
              <span className="flex gap-2">
                <button className="text-primary hover:underline" onClick={() => restoreDraft(selected!)}>
                  恢复草稿
                </button>
                <button className="text-muted-foreground hover:underline" onClick={() => discardDraft(selected!)}>
                  忽略
                </button>
              </span>
            </div>
          )}

          {/* 版本 diff */}
          {diff && parsed && doc?.content ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">版本对比：当前编辑 vs {diff.version}</span>
                <Button size="sm" variant="ghost" onClick={() => showDiff(selected!, diff.version)}>
                  关闭对比
                </Button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Card>
                  <CardContent className="p-3">
                    <pre className="max-h-[400px] overflow-auto whitespace-pre-wrap rounded bg-muted/20 p-2 font-mono text-xs text-muted-foreground">{diff.content}</pre>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-3">
                    <pre className="max-h-[400px] overflow-auto whitespace-pre-wrap rounded bg-muted/20 p-2 font-mono text-xs text-muted-foreground">{currentYaml}</pre>
                  </CardContent>
                </Card>
              </div>
            </div>
          ) : !selected ? (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                从左侧选择资产开始编辑，或点「新建」创建
              </CardContent>
            </Card>
          ) : isSpecial && doc?.content ? (
            <fieldset disabled={!canEdit} className="m-0 border-0 p-0">
              {selected === "policy" && (
                <AggregationPolicyEditor
                  scenarioId={id}
                  data={(doc.content.aggregation_policy as Record<string, unknown>) ?? {}}
                  onChange={(p) => updateDoc(selected, { ...doc.content, aggregation_policy: p } as Dict)}
                />
              )}
              {selected === "metrics" && (
                <MetricDefsEditor
                  scenarioId={id}
                  data={(doc.content.metric_definitions as unknown as MetricDef[]) ?? []}
                  onChange={(m) => updateDoc(selected, { ...doc.content, metric_definitions: m } as Dict)}
                />
              )}
            </fieldset>
          ) : isSpecial ? (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">加载中…</CardContent>
            </Card>
          ) : !doc || doc.content == null ? (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">加载中…</CardContent>
            </Card>
          ) : mode === "form" ? (
            <fieldset disabled={!canEdit} className="m-0 border-0 p-0">
              {parsed?.kind === "rule-sets" && (
                <RuleSetForm
                  data={doc.content as unknown as RuleSetData}
                  onChange={(d) => updateDoc(selected, d as unknown as Dict)}
                  prompts={catalog?.prompts ?? []}
                  datasets={(catalog?.datasets ?? []).filter((d) => d.role === "reference")}
                  onNewPromptForRule={(i, field) => createAndBindPrompt(selected, i, field)}
                  onNewDataset={() => createAsset("datasets")}
                  onJumpAsset={jumpAsset}
                />
              )}
              {parsed?.kind === "prompts" && (
                <PromptForm data={doc.content as unknown as PromptData} onChange={(d) => updateDoc(selected, d as unknown as Dict)} scenarioId={id} />
              )}
              {parsed?.kind === "datasets" && (
                <DatasetForm data={doc.content as unknown as DatasetData} onChange={(d) => updateDoc(selected, d as unknown as Dict)} />
              )}
            </fieldset>
          ) : (
            <Card>
              <CardContent>
                <Textarea className="min-h-[500px] font-mono text-xs leading-relaxed" value={currentYaml} readOnly={!canEdit} onChange={(e) => onYamlChange(e.target.value)} />
              </CardContent>
            </Card>
          )}

        </div>

        {/* ── 右侧：版本时间线 + 配置完整度（规则集时） ── */}
        {selected && doc && (
          <div className="space-y-4 lg:sticky lg:top-[72px] lg:max-h-[calc(100vh-88px)] lg:overflow-y-auto">
            <VersionTimeline
              doc={doc}
              dirty={dirtyOf(selected)}
              busy={busy}
              canEdit={canEdit}
              missingRefs={refs}
              onPublish={(labels, withRefs) => publish(selected, labels, { withRefs })}
              onPromote={(ver, lbl) => promote(selected, ver, lbl)}
              onDiff={(ver) => showDiff(selected, ver)}
              onVersionChange={(v) => setNextVersion(selected, v)}
            />
            {parsed?.kind === "rule-sets" && doc.content && (
              <CompletenessPanel data={doc.content as unknown as RuleSetData} metricCount={metricCount} hasPolicy={hasPolicy} />
            )}
          </div>
        )}
      </div>
    </Page>
  )
}
