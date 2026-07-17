import { useEffect, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { useCrumbs } from "../../context/navigation"
import { Page, PageHead, DataTable } from "../../components/shared"
import { Card, CardContent } from "../../components/shadcn/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/shadcn/tabs"
import { Badge } from "../../components/shadcn/badge"
import { Button } from "../../components/shadcn/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/shadcn/dialog"
import { Input } from "../../components/shadcn/input"
import { Label } from "../../components/shadcn/label"
import { Textarea } from "../../components/shadcn/textarea"
import { toast } from "sonner"
import { api, type ScenarioCatalog, type CatalogEntry, type DatasetCatalogEntry } from "../../api/client"
import { Package, Pencil, Plus } from "lucide-react"

const VERSION_LABELS = ["production", "staging", "latest"] as const

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
            <Button variant="outline" onClick={() => nav(`/config/scenarios/${id}/edit`)}>
              <Pencil className="size-4" /> 进入包编辑器
            </Button>
            <Button onClick={() => setPublishOpen(true)}>
              <Plus className="size-4" /> 发布包版本
            </Button>
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
        </Tabs>
      ) : null}

      <PublishDialog open={publishOpen} onOpenChange={setPublishOpen} scenarioId={id} />
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
          render: (r) => (
            <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={(e) => { e.stopPropagation(); onOpen(r.asset_id) }}>
              <Pencil className="size-3" /> 编辑
            </Button>
          ),
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
          render: (r) => (
            <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={(e) => { e.stopPropagation(); onOpen(r.asset_id) }}>
              <Pencil className="size-3" /> 编辑
            </Button>
          ),
        },
      ]}
      rowKey={(r) => `${r.role}-${r.asset_id}`}
    />
  )
}

function PublishDialog({
  open,
  onOpenChange,
  scenarioId,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  scenarioId: string
}) {
  const [assetId, setAssetId] = useState("")
  const [version, setVersion] = useState("1.0.0")
  const [label, setLabel] = useState<string>("production")
  const [name, setName] = useState("")
  const [yaml, setYaml] = useState("package:\n  id: \n  scenario: \n  version: 1.0.0\n")
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true)
    try {
      // 前端把整段 YAML manifest 文本存入 content，由后端解析
      const content: Record<string, unknown> = { manifest_yaml: yaml }
      await api.publishPackage(scenarioId, {
        asset_id: assetId,
        version,
        labels: label ? [label] : [],
        name: name || undefined,
        content,
      })
      toast.success("包版本已发布")
      onOpenChange(false)
    } catch (e) {
      toast.error(errMsg(e, "发布失败"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="size-4" /> 发布场景包版本
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>包 ID (asset_id)</Label>
              <Input value={assetId} onChange={(e) => setAssetId(e.target.value)} placeholder="如 quality" />
            </div>
            <div className="space-y-1">
              <Label>版本</Label>
              <Input value={version} onChange={(e) => setVersion(e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>标签</Label>
              <select
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              >
                <option value="">（无）</option>
                {VERSION_LABELS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label>展示名</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="可选" />
            </div>
          </div>
          <div className="space-y-1">
            <Label>清单 (agent_eval.yaml)</Label>
            <Textarea
              className="font-mono text-xs"
              rows={8}
              value={yaml}
              onChange={(e) => setYaml(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={submit} disabled={busy || !assetId || !version}>
            {busy ? "发布中…" : "发布"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
