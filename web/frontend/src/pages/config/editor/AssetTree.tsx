/**
 * 统一编辑器左侧资产树（docs/arch/13 §6.2）。
 *
 * 分组展示规则集/提示词/数据集/策略；新建按钮创建本地 isNew 草稿（标记「未发布」）；
 * 节点显示 dirty 圆点（有未保存改动）与草稿/未发布标记。
 */
import { BookOpen, ChevronRight, ClipboardList, Database, FileText, Gauge, Layers, Plug } from "lucide-react"
import type {
  AssetKind,
  CatalogEntry,
  DatasetCatalogEntry,
  SutCatalogEntry,
  TaskSetCatalogEntry,
} from "../../../api/client"
import { AddButton } from "../../../components/shared"
import type { DocState, Selection } from "./types"

export interface TreeCatalog {
  rule_sets: CatalogEntry[]
  prompts: CatalogEntry[]
  datasets: DatasetCatalogEntry[]
  task_sets: TaskSetCatalogEntry[]
  sut_configs: SutCatalogEntry[]
}

interface TreeProps {
  catalog: TreeCatalog | null
  docs: Record<Selection, DocState>
  selected: Selection | null
  dirtyOf: (sel: Selection) => boolean
  onSelect: (sel: Selection) => void
  onCreate: (kind: AssetKind) => void
  canEdit: boolean
}

export function AssetTree({ catalog, docs, selected, dirtyOf, onSelect, onCreate, canEdit }: TreeProps) {
  // 本地新建（未发布）资产：在树中追加展示
  const newDocs = (kind: AssetKind) =>
    Object.values(docs).filter((d) => d.isNew && d.kind === kind)

  const node = (sel: Selection, name: string, icon: typeof FileText, mark?: "new" | "draft") => (
    <TreeNode
      key={sel}
      active={selected === sel}
      name={name}
      icon={icon}
      dirty={dirtyOf(sel)}
      mark={mark}
      onClick={() => onSelect(sel)}
    />
  )

  return (
    <div className="space-y-4">
      <TreeSection icon={Layers} label="规则集">
        {catalog?.rule_sets.length === 0 && newDocs("rule-sets").length === 0 && (
          <p className="px-2 py-1 text-[11px] text-muted-foreground/60">暂无规则集，点下方新建</p>
        )}
        {catalog?.rule_sets.map((r) => node(`rule-sets:${r.asset_id}`, r.asset_id, FileText))}
        {newDocs("rule-sets").map((d) => node(`rule-sets:${d.assetId}`, d.assetId, FileText, "new"))}
        {canEdit && (
          <AddButton className="mt-1 w-full justify-start" onClick={() => onCreate("rule-sets")}>
            新建规则集
          </AddButton>
        )}
      </TreeSection>
      <TreeSection icon={BookOpen} label="提示词">
        {catalog?.prompts.length === 0 && newDocs("prompts").length === 0 && (
          <p className="px-2 py-1 text-[11px] text-muted-foreground/60">暂无提示词</p>
        )}
        {catalog?.prompts.map((p) => node(`prompts:${p.asset_id}`, p.asset_id, FileText))}
        {newDocs("prompts").map((d) => node(`prompts:${d.assetId}`, d.assetId, FileText, "new"))}
        {canEdit && (
          <AddButton className="mt-1 w-full justify-start" onClick={() => onCreate("prompts")}>
            新建提示词
          </AddButton>
        )}
      </TreeSection>
      <TreeSection icon={Database} label="参考数据">
        {catalog?.datasets.length === 0 && newDocs("datasets").length === 0 && (
          <p className="px-2 py-1 text-[11px] text-muted-foreground/60">暂无数据集</p>
        )}
        {catalog?.datasets.map((d) => node(`datasets:${d.asset_id}`, d.asset_id, Database))}
        {newDocs("datasets").map((d) => node(`datasets:${d.assetId}`, d.assetId, Database, "new"))}
        {canEdit && (
          <AddButton className="mt-1 w-full justify-start" onClick={() => onCreate("datasets")}>
            新建数据集
          </AddButton>
        )}
      </TreeSection>
      <TreeSection icon={ClipboardList} label="任务集（考卷）">
        {catalog?.task_sets.length === 0 && newDocs("task-sets").length === 0 && (
          <p className="px-2 py-1 text-[11px] text-muted-foreground/60">暂无任务集（考卷）</p>
        )}
        {catalog?.task_sets.map((t) => node(`task-sets:${t.asset_id}`, t.asset_id, ClipboardList))}
        {newDocs("task-sets").map((d) => node(`task-sets:${d.assetId}`, d.assetId, ClipboardList, "new"))}
        {canEdit && (
          <AddButton className="mt-1 w-full justify-start" onClick={() => onCreate("task-sets")}>
            新建任务集
          </AddButton>
        )}
      </TreeSection>
      <TreeSection icon={Plug} label="SUT 接入">
        {catalog?.sut_configs.length === 0 && newDocs("sut-configs").length === 0 && (
          <p className="px-2 py-1 text-[11px] text-muted-foreground/60">暂无 SUT 接入配置</p>
        )}
        {catalog?.sut_configs.map((s) => node(`sut-configs:${s.asset_id}`, s.asset_id, Plug))}
        {newDocs("sut-configs").map((d) => node(`sut-configs:${d.assetId}`, d.assetId, Plug, "new"))}
        {canEdit && (
          <AddButton className="mt-1 w-full justify-start" onClick={() => onCreate("sut-configs")}>
            新建 SUT 配置
          </AddButton>
        )}
      </TreeSection>
      <TreeSection icon={Gauge} label="策略">
        <TreeNode active={selected === "metrics"} name="指标定义" icon={Layers} onClick={() => onSelect("metrics")} />
        <TreeNode active={selected === "policy"} name="聚合策略" icon={Gauge} onClick={() => onSelect("policy")} />
      </TreeSection>
    </div>
  )
}

function TreeSection({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof FileText
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1 px-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon className="size-3" />
        {label}
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

function TreeNode({
  active,
  name,
  icon: Icon,
  dirty,
  mark,
  onClick,
}: {
  active: boolean
  name: string
  icon: typeof FileText
  dirty?: boolean
  mark?: "new" | "draft"
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left text-xs transition-colors ${
        active ? "bg-primary/15 font-medium text-primary" : "text-muted-foreground hover:bg-accent/50"
      }`}
    >
      <Icon className="size-3 shrink-0 opacity-60" />
      <span className="flex-1 truncate font-mono">{name}</span>
      {mark === "new" && (
        <span className="shrink-0 rounded-sm bg-warning/15 px-1 py-px text-[9px] font-semibold text-warning">未发布</span>
      )}
      {dirty && <span className="size-1.5 shrink-0 rounded-full bg-warning" title="有未保存改动" />}
      {active && <ChevronRight className="size-3 shrink-0" />}
    </button>
  )
}
