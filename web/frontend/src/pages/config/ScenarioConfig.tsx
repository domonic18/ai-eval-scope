import { useEffect, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { useCrumbs } from "../../context/navigation"
import { Page, PageHead, DataTable } from "../../components/shared"
import { Card, CardContent } from "../../components/shadcn/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/shadcn/tabs"
import { Badge } from "../../components/shadcn/badge"
import { Button } from "../../components/shadcn/button"
import { api, type ScenarioCatalog, type CatalogEntry, type DatasetCatalogEntry, type SutCatalogEntry, type TaskSetCatalogEntry } from "../../api/client"
import { canEditConfig } from "../../store/auth"
import { Pencil, Plus } from "lucide-react"
import { PublishPackageDialog } from "./PublishPackageDialog"

const errMsg = (e: unknown, fb: string) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb

export default function ScenarioConfig() {
  const { id = "" } = useParams()
  const nav = useNavigate()
  const { setCrumbs } = useCrumbs()
  const [catalog, setCatalog] = useState<ScenarioCatalog | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [publishOpen, setPublishOpen] = useState(false)

  useEffect(() => {
    setCrumbs([{ label: "配置中心", to: "/config" }, { label: id }])
    api
      .scenarioCatalog(id)
      .then(setCatalog)
      .catch((e) => setError(errMsg(e, "加载 catalog 失败")))
      .finally(() => setLoading(false))
  }, [id, setCrumbs])

  return (
    <Page>
      <PageHead
        title={catalog?.scenario.name ?? id}
        sub={catalog?.scenario.description ?? `场景 ${id} 的规则集 / 提示词 / 数据集`}
        right={
          <div className="flex gap-2">
            {canEditConfig() && (
              <>
                <Button variant="outline" onClick={() => nav(`/config/scenarios/${id}/edit`)}>
                  <Pencil className="size-4" /> 进入包编辑器
                </Button>
                <Button onClick={() => setPublishOpen(true)}>
                  <Plus className="size-4" /> 发布包版本
                </Button>
              </>
            )}
          </div>
        }
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
            <EntryTable
              rows={catalog.rule_sets}
              emptyHint="无规则集"
              onOpen={(aid) => nav(`/config/scenarios/${id}/edit?select=rule-sets:${aid}`)}
            />
          </TabsContent>
          <TabsContent value="prompts">
            <EntryTable
              rows={catalog.prompts}
              emptyHint="无提示词"
              onOpen={(aid) => nav(`/config/scenarios/${id}/edit?select=prompts:${aid}`)}
            />
          </TabsContent>
          <TabsContent value="datasets">
            <DatasetTable rows={catalog.datasets} onOpen={(aid) => nav(`/config/scenarios/${id}/edit?select=datasets:${aid}`)} />
          </TabsContent>
          <TabsContent value="task_sets">
            <TaskSetTable
              rows={catalog.task_sets ?? []}
              onOpen={(aid) => nav(`/config/scenarios/${id}/edit?select=task-sets:${aid}`)}
            />
          </TabsContent>
          <TabsContent value="sut_configs">
            <SutTable
              rows={catalog.sut_configs ?? []}
              onOpen={(aid) => nav(`/config/scenarios/${id}/edit?select=sut-configs:${aid}`)}
            />
          </TabsContent>
        </Tabs>
      ) : null}

      <PublishPackageDialog open={publishOpen} onOpenChange={setPublishOpen} scenarioId={id} />
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
        {
          key: "actions",
          title: "",
          render: (r) =>
            canEditConfig() ? (
              <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={(e) => { e.stopPropagation(); onOpen(r.asset_id) }}>
                <Pencil className="size-3" /> 编辑
              </Button>
            ) : null,
        },
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
        {
          key: "actions",
          title: "",
          render: (r) =>
            canEditConfig() ? (
              <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={(e) => { e.stopPropagation(); onOpen(r.asset_id) }}>
                <Pencil className="size-3" /> 编辑
              </Button>
            ) : null,
        },
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
        {
          key: "actions",
          title: "",
          render: (r) =>
            canEditConfig() ? (
              <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={(e) => { e.stopPropagation(); onOpen(r.asset_id) }}>
                <Pencil className="size-3" /> 编辑
              </Button>
            ) : null,
        },
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
        {
          key: "actions",
          title: "",
          render: (r) =>
            canEditConfig() ? (
              <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={(e) => { e.stopPropagation(); onOpen(r.asset_id) }}>
                <Pencil className="size-3" /> 编辑
              </Button>
            ) : null,
        },
      ]}
      rowKey={(r) => r.asset_id}
    />
  )
}
