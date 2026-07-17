/** 超管后台 · 项目管理：跨组织项目列表 + 归档过滤 + 删除。 */
import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api, type AdminProject } from "../../api/client"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/shadcn/select"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import { useToast } from "../../hooks/useToast"
import { DataTable, Page, PageHead, Pager, type Column } from "../../components/shared"
import { timeAgo } from "../../lib/format"
import { useDebouncedValue } from "../../lib/useDebounce"

export default function AdminProjects() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminProject[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [archived, setArchived] = useState("all")
  const debouncedSearch = useDebouncedValue(search, 300)
  const [delTarget, setDelTarget] = useState<AdminProject | null>(null)
  const [busy, setBusy] = useState(false)

  async function load(p = 1) {
    try {
      const r = await api.adminListProjects({
        search: debouncedSearch || undefined,
        archived: archived === "all" ? undefined : archived === "true",
        page: p,
      })
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
    } catch {
      toast.error("加载项目失败")
    }
  }
  useEffect(() => {
    load(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch, archived])

  async function confirmDelete() {
    if (!delTarget) return
    setBusy(true)
    try {
      await api.adminDeleteProject(delTarget.id)
      toast.success("已删除")
      setDelTarget(null)
      await load()
    } catch {
      toast.error("删除失败")
    } finally {
      setBusy(false)
    }
  }

  const columns: Column<AdminProject>[] = [
    {
      key: "name",
      title: "项目",
      render: (p) => (
        <div>
          <div>{p.name}</div>
          <div className="text-xs text-muted-foreground">{p.slug}</div>
        </div>
      ),
    },
    { key: "org", title: "工作组", render: (p) => p.org.name },
    { key: "runs", title: "运行", num: true, render: (p) => p._count.runs },
    { key: "keys", title: "API Key", num: true, render: (p) => p._count.apiKeys },
    {
      key: "status",
      title: "状态",
      render: (p) =>
        p.archivedAt ? (
          <span className="text-xs text-muted-foreground">已归档</span>
        ) : (
          <span className="inline-flex items-center rounded-md border border-emerald-500/40 px-2 py-0.5 text-xs font-medium text-emerald-400">
            活跃
          </span>
        ),
    },
    { key: "created", title: "创建", render: (p) => timeAgo(p.createdAt) },
    {
      key: "actions",
      title: "操作",
      render: (p) => (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link to={`/project/${p.id}`}>查看</Link>
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-red-400"
            onClick={() => setDelTarget(p)}
          >
            删除
          </Button>
        </div>
      ),
    },
  ]

  return (
    <Page>
      <PageHead title="项目管理" sub={`共 ${total} 个项目（跨所有工作组）`} />
      <div className="space-y-3 rounded-lg border bg-card p-4 text-card-foreground">
        <div className="flex gap-2">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="名称 / slug"
          />
          <Select value={archived} onValueChange={setArchived}>
            <SelectTrigger className="w-32">
              <SelectValue placeholder="全部" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部</SelectItem>
              <SelectItem value="false">活跃</SelectItem>
              <SelectItem value="true">已归档</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <DataTable columns={columns} rows={rows} rowKey={(p) => p.id} />
        <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
      </div>

      <Dialog open={!!delTarget} onOpenChange={(o) => !o && setDelTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除项目</DialogTitle>
            <DialogDescription>
              确认删除项目 <strong>{delTarget?.name}</strong>？其下所有运行、样本、产出物与 API Key
              将一并级联删除，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDelTarget(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={busy}>
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  )
}
