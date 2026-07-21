/**
 * 统一编辑器右侧：版本时间线 + 发布设置（docs/arch/14 §6.2）。
 *
 * 顶部：版本号 + 标签（多选）+ 发布按钮（规则集存在未发布引用时提供「连同引用一起发布」）；
 * 当前编辑卡 + 已发布版本卡（对比/晋升）。
 */
import { useState } from "react"
import { GitBranch, GitCompare, ArrowUpCircle, Upload } from "lucide-react"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Label } from "../../../components/shadcn/label"
import { SectionCard, SectionCardContent, SectionCardHeader, SectionCardTitle } from "../../../components/shared"
import { relTime, VERSION_LABELS, type DocState, type Selection } from "./types"

export function VersionTimeline({
  doc,
  dirty,
  busy,
  missingRefs,
  onPublish,
  onPromote,
  onDiff,
  onVersionChange,
}: {
  doc: DocState
  dirty: boolean
  busy: boolean
  missingRefs: { prompts: string[]; datasets: string[]; unpublished: Selection[] }
  onPublish: (labels: string[], withRefs: boolean) => void
  onPromote: (ver: string, lbl: string) => void
  onDiff: (ver: string) => void
  onVersionChange: (v: string) => void
}) {
  const [labels, setLabels] = useState<string[]>([])
  const toggleLabel = (l: string) =>
    setLabels((prev) => (prev.includes(l) ? prev.filter((x) => x !== l) : [...prev, l]))

  const blockedByMissing = missingRefs.prompts.length > 0 || missingRefs.datasets.length > 0
  const hasUnpublishedRefs = missingRefs.unpublished.length > 0

  return (
    <SectionCard className="h-fit">
      <SectionCardHeader>
        <SectionCardTitle className="flex items-center gap-1.5">
          <GitBranch className="size-4" />
          版本时间线
        </SectionCardTitle>
        <Button size="sm" variant="outline" disabled={busy || blockedByMissing} onClick={() => onPublish(labels, hasUnpublishedRefs)}>
          <Upload className="mr-1 size-3" />
          {hasUnpublishedRefs ? "连同引用一起发布" : "发布新版本"}
        </Button>
      </SectionCardHeader>
      <SectionCardContent className="space-y-2">
        {/* 发布设置 */}
        <div className="space-y-2 border-b border-border pb-3">
          <div>
            <Label className="text-[11px] text-muted-foreground">版本号</Label>
            <Input
              value={doc.nextVersion}
              onChange={(e) => onVersionChange(e.target.value)}
              placeholder="1.0.0"
              className="mt-1 h-8 font-mono text-xs"
            />
          </div>
          <div>
            <Label className="text-[11px] text-muted-foreground">标签（可多选）</Label>
            <div className="mt-1 flex gap-1.5">
              {VERSION_LABELS.map((l) => {
                const on = labels.includes(l)
                return (
                  <button
                    key={l}
                    type="button"
                    onClick={() => toggleLabel(l)}
                    className={`rounded-md border px-2 py-0.5 text-[11px] transition-colors ${
                      on ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {l}
                  </button>
                )
              })}
            </div>
          </div>
          {blockedByMissing && (
            <p className="text-[11px] text-destructive">
              引用不存在：{[...missingRefs.prompts, ...missingRefs.datasets].join("、")}，无法发布
            </p>
          )}
          {hasUnpublishedRefs && !blockedByMissing && (
            <p className="text-[11px] text-warning">
              {missingRefs.unpublished.length} 个引用资产未发布，将一并发布（无标签）
            </p>
          )}
        </div>

        <div className="max-h-[calc(100vh-420px)] space-y-2 overflow-y-auto pr-1">
          {/* 当前编辑卡 */}
          <div className="rounded-md border border-primary/40 bg-linear-to-b from-primary/10 to-transparent p-2 ring-1 ring-primary/20">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs font-medium">{doc.nextVersion || "草稿"}</span>
              <span className="rounded-sm bg-warning/15 px-1.5 py-px text-[9px] font-semibold text-warning">
                {doc.isNew ? "未发布" : "编辑中"}
              </span>
            </div>
            <p className="mt-0.5 text-[10px] text-muted-foreground">{dirty ? "有未保存改动" : "已与已发布一致"}</p>
          </div>

          {/* 已发布版本 */}
          {doc.versions.length === 0 && !doc.isNew ? (
            <p className="text-xs text-muted-foreground">暂无历史版本</p>
          ) : (
            doc.versions.map((v) => (
              <div key={v.version} className="rounded-md border border-border p-2 transition-colors hover:border-primary/30">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-medium">{v.version}</span>
                  <div className="flex gap-0.5">
                    {v.labels.map((l) => (
                      <span
                        key={l}
                        className={`rounded-sm px-1.5 py-px font-mono text-[9px] font-semibold ${
                          l === "production" ? "bg-success/15 text-success" : l === "staging" ? "bg-warning/15 text-warning" : "bg-info/15 text-info"
                        }`}
                      >
                        {l}
                      </span>
                    ))}
                  </div>
                </div>
                <p className="mt-0.5 truncate font-mono text-[9px] text-muted-foreground">{v.contentHash}</p>
                <p className="mt-0.5 text-[9px] text-muted-foreground">{relTime(v.createdAt)}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  <button onClick={() => onDiff(v.version)} className="inline-flex items-center gap-0.5 rounded-sm px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-accent hover:text-foreground">
                    <GitCompare className="size-3" />
                    对比
                  </button>
                  {VERSION_LABELS.filter((l) => !v.labels.includes(l)).map((l) => (
                    <button key={l} onClick={() => onPromote(v.version, l)} className="inline-flex items-center gap-0.5 rounded-sm px-1.5 py-0.5 text-[10px] text-primary hover:bg-primary/10">
                      <ArrowUpCircle className="size-3" />
                      晋升{l}
                    </button>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </SectionCardContent>
    </SectionCard>
  )
}
