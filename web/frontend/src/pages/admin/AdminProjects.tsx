/** 超管后台 · 项目管理：跨组织项目列表 + 归档过滤。 */
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
import { useToast } from "../../components/toast"
import { DataTable, PageHead, Pager, type Column } from "../../components/shared"
import { timeAgo } from "../../lib/format"

export default function AdminProjects() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminProject[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [archived, setArchived] = useState<string>("")

  async function load(p = 1) {
    try {
      const r = await api.adminListProjects({
        search: search || undefined,
        archived: archived === "" ? undefined : archived === "true",
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
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
      key: "go",
      title: "",
      render: (p) => (
        <Button variant="outline" size="sm" asChild>
          <Link to={`/project/${p.id}`}>查看</Link>
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6 p-6">
      <PageHead title="项目管理" sub={`共 ${total} 个项目（跨所有工作组）`} />
      <div className="space-y-3 rounded-lg border bg-card p-4 text-card-foreground">
        <div className="flex gap-2">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="名称 / slug"
            onKeyDown={(e) => e.key === "Enter" && load(1)}
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
          <Button onClick={() => load(1)}>筛选</Button>
        </div>
        <DataTable columns={columns} rows={rows} rowKey={(p) => p.id} />
        <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
      </div>
    </div>
  )
}
