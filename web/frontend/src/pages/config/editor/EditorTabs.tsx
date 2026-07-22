/**
 * 编辑器 Tab 栏（docs/arch/13 §5.1）。
 *
 * 已打开资产以 Tab 呈现，dirty 圆点提示未保存；关闭仅从 Tab 列表移除，文档保留在内存（不丢改动）。
 */
import { X } from "lucide-react"
import type { DocState, Selection } from "./types"

const KIND_SHORT: Record<string, string> = {
  "rule-sets": "规则",
  prompts: "提示词",
  datasets: "数据",
}

export function EditorTabs({
  tabs,
  docs,
  selected,
  dirtyOf,
  onSelect,
  onClose,
}: {
  tabs: Selection[]
  docs: Record<Selection, DocState>
  selected: Selection | null
  dirtyOf: (sel: Selection) => boolean
  onSelect: (sel: Selection) => void
  onClose: (sel: Selection) => void
}) {
  if (tabs.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-1">
      {tabs.map((sel) => {
        const doc = docs[sel]
        const label = doc ? doc.assetId : sel.split(":").slice(1).join(":")
        const kind = sel.split(":")[0]
        const active = selected === sel
        const dirty = dirtyOf(sel)
        return (
          <span
            key={sel}
            className={`group inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition-colors ${
              active ? "border-primary/50 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            <button type="button" onClick={() => onSelect(sel)} className="inline-flex items-center gap-1">
              <span className="opacity-60">{KIND_SHORT[kind] ?? kind}</span>
              <span className="font-mono">{label}</span>
              {dirty && <span className="size-1.5 rounded-full bg-warning" title="有未保存改动" />}
            </button>
            <button
              type="button"
              onClick={() => onClose(sel)}
              className="rounded p-0.5 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
              title="关闭（改动保留在内存中）"
            >
              <X className="size-3" />
            </button>
          </span>
        )
      })}
    </div>
  )
}
