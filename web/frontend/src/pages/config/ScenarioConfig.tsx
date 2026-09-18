import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { useCrumbs } from "../../context/navigation"
import { Page, PageHead, DataTable } from "../../components/shared"
import { Card, CardContent } from "../../components/shadcn/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/shadcn/tabs"
import { Badge } from "../../components/shadcn/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../../components/shadcn/dialog"
import { api, type AssetKind, type ScenarioCatalog, type CatalogEntry, type DatasetCatalogEntry, type SutCatalogEntry, type TaskSetCatalogEntry } from "../../api/client"

const errMsg = (e: unknown, fb: string) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb

/** catalog 表键 → API 资产 kind（GET /scenarios/:id/:kind/:assetId/content）。 */
const CATALOG_KIND: Record<string, AssetKind> = {
  rules: "rule-sets",
  prompts: "prompts",
  datasets: "datasets",
  task_sets: "task-sets",
  sut_configs: "sut-configs",
}

/** 只读内容弹窗（docs/plan/08 纯可视化：场景包仅查看）。 */
function AssetContentDialog({
  scenarioId,
  target,
  onClose,
}: {
  scenarioId: string
  target: { kind: AssetKind; assetId: string } | null
  onClose: () => void
}) {
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setContent(null)
    setError(null)
    if (!target) return
    api
      .assetContent(scenarioId, target.kind, target.assetId)
      .then((c) => setContent(JSON.stringify(c, null, 2)))
      .catch((e) => setError(errMsg(e, "加载资产内容失败")))
  }, [scenarioId, target])

  return (
    <Dialog open={target != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="font-mono text-sm">{target?.assetId}</DialogTitle>
          <DialogDescription>资产内容（只读，登记源以仓库 YAML 为准）</DialogDescription>
        </DialogHeader>
        {error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">{error}</div>
        ) : content == null ? (
          <div className="py-6 text-sm text-muted-foreground">加载中…</div>
        ) : (
          <pre className="max-h-[60vh] overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
            {content}
          </pre>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default function ScenarioConfig() {
  const { id = "" } = useParams()
  const { setCrumbs } = useCrumbs()
  const [catalog, setCatalog] = useState<ScenarioCatalog | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // 只读查看：当前点选的资产（null = 关闭）
  const [viewing, setViewing] = useState<{ kind: AssetKind; assetId: string } | null>(null)

  useEffect(() => {
    setCrumbs([{ label: "配置中心", to: "/config" }, { label: id }])
    api
      .scenarioCatalog(id)
      .then(setCatalog)
      .catch((e) => setError(errMsg(e, "加载 catalog 失败")))
      .finally(() => setLoading(false))
  }, [id, setCrumbs])

  const openAsset = (tab: string, assetId: string) =>
    setViewing({ kind: CATALOG_KIND[tab] ?? "rule-sets", assetId })

  return (
    <Page>
      <PageHead
        title={catalog?.scenario.name ?? id}
        sub={catalog?.scenario.description ?? `场景 ${id} 的规则集 / 提示词 / 数据集（只读目录）`}
      />
      {error && <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">{error}</div>}
      {loading ? (
        <div className="text-sm text-muted-foreground">加载中…</div>
      ) : catalog ? (
        <Tabs defaultValue="rules">
          <TabsList>
            <TabsTrigger value="rules">规则集 ({catalog.rule_sets.length})</TabsTrigger>
            <TabsTrigger value="prompts">提示词 ({catalog.prompts.length})</TabsTrigger>
            <TabsTrigger value="datasets">数据集 ({catalog.datasets.length})</TabsTrigger>
            <TabsTrigger value="task_sets">任务集 ({catalog.task_sets?.length ?? 0})</TabsTrigger>
            <TabsTrigger value="sut_configs">SUT 接入 ({catalog.sut_configs?.length ?? 0})</TabsTrigger>
          </TabsList>
          <TabsContent value="rules">
            <EntryTable rows={catalog.rule_sets} emptyHint="无规则集" onOpen={(aid) => openAsset("rules", aid)} />
          </TabsContent>
          <TabsContent value="prompts">
            <EntryTable rows={catalog.prompts} emptyHint="无提示词" onOpen={(aid) => openAsset("prompts", aid)} />
          </TabsContent>
          <TabsContent value="datasets">
            <DatasetTable rows={catalog.datasets} onOpen={(aid) => openAsset("datasets", aid)} />
          </TabsContent>
          <TabsContent value="task_sets">
            <TaskSetTable rows={catalog.task_sets ?? []} onOpen={(aid) => openAsset("task_sets", aid)} />
          </TabsContent>
          <TabsContent value="sut_configs">
            <SutTable rows={catalog.sut_configs ?? []} onOpen={(aid) => openAsset("sut_configs", aid)} />
          </TabsContent>
        </Tabs>
      ) : null}

      <AssetContentDialog scenarioId={id} target={viewing} onClose={() => setViewing(null)} />
    </Page>
  )
}

function EntryTable({
  rows,
  emptyHint,
  onOpen,
}: {
  rows: CatalogEntry[]
  emptyHint: string
  onOpen: (assetId: string) => void
}) {
  if (rows.length === 0)
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">{emptyHint}</CardContent>
      </Card>
    )
  return (
    <DataTable
      rows={rows}
      onRowClick={(r) => onOpen(r.asset_id)}
      columns={[
        { key: "asset_id", title: "ID", render: (r) => <span className="font-mono text-xs">{r.asset_id}</span> },
        { key: "name", title: "名称", render: (r) => r.name ?? "—" },
        { key: "version", title: "版本", render: (r) => <Badge variant="secondary">{r.version}</Badge> },
        {
          key: "labels",
          title: "标签",
          render: (r) => (
            <div className="flex gap-1">
              {r.labels.map((l) => (
                <Badge key={l} variant="outline" className="text-xs">
                  {l}
                </Badge>
              ))}
            </div>
          ),
        },
        { key: "description", title: "描述", render: (r) => <span className="text-muted-foreground">{r.description ?? "—"}</span> },
      ]}
      rowKey={(r) => r.asset_id}
    />
  )
}

function DatasetTable({ rows, onOpen }: { rows: DatasetCatalogEntry[]; onOpen: (assetId: string) => void }) {
  if (rows.length === 0)
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">无数据集</CardContent>
      </Card>
    )
  return (
    <DataTable
      rows={rows}
      onRowClick={(r) => onOpen(r.asset_id)}
      columns={[
        { key: "asset_id", title: "ID", render: (r) => <span className="font-mono text-xs">{r.asset_id}</span> },
        {
          key: "role",
          title: "角色",
          render: (r) => (
            <Badge variant={r.role === "test" ? "default" : "secondary"}>{r.role}</Badge>
          ),
        },
        { key: "backend_type", title: "后端", render: (r) => <span className="font-mono text-xs">{r.backend_type}</span> },
        { key: "version", title: "版本", render: (r) => <Badge variant="secondary">{r.version}</Badge> },
        { key: "description", title: "描述", render: (r) => <span className="text-muted-foreground">{r.description ?? "—"}</span> },
      ]}
      rowKey={(r) => `${r.role}-${r.asset_id}`}
    />
  )
}

function TaskSetTable({ rows, onOpen }: { rows: TaskSetCatalogEntry[]; onOpen: (assetId: string) => void }) {
  if (rows.length === 0)
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">无任务集（考卷）</CardContent>
      </Card>
    )
  return (
    <DataTable
      rows={rows}
      onRowClick={(r) => onOpen(r.asset_id)}
      columns={[
        { key: "asset_id", title: "ID", render: (r) => <span className="font-mono text-xs">{r.asset_id}</span> },
        { key: "name", title: "名称", render: (r) => r.name ?? "—" },
        { key: "task_count", title: "任务数", render: (r) => <Badge variant="secondary">{r.task_count}</Badge> },
        { key: "version", title: "版本", render: (r) => <Badge variant="secondary">{r.version}</Badge> },
        { key: "description", title: "描述", render: (r) => <span className="text-muted-foreground">{r.description ?? "—"}</span> },
      ]}
      rowKey={(r) => r.asset_id}
    />
  )
}

function SutTable({ rows, onOpen }: { rows: SutCatalogEntry[]; onOpen: (assetId: string) => void }) {
  if (rows.length === 0)
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">无 SUT 接入配置</CardContent>
      </Card>
    )
  return (
    <DataTable
      rows={rows}
      onRowClick={(r) => onOpen(r.asset_id)}
      columns={[
        { key: "asset_id", title: "SUT", render: (r) => <span className="font-mono text-xs">{r.asset_id}</span> },
        { key: "channel", title: "通道", render: (r) => <Badge variant="secondary">{r.channel ?? "—"}</Badge> },
        { key: "version", title: "版本", render: (r) => <Badge variant="secondary">{r.version}</Badge> },
        { key: "description", title: "描述", render: (r) => <span className="text-muted-foreground">{r.description ?? "—"}</span> },
      ]}
      rowKey={(r) => r.asset_id}
    />
  )
}
