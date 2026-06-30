/** 超管后台 · 项目管理：跨组织项目列表 + 归档过滤。 */
import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api, type AdminProject } from "../../api/client"
import { Badge, Button, DataTable, Field, Input, useToast, type Column } from "../../components/ui"
import { timeAgo } from "../../lib/format"
import { Pager } from "./AdminUsers"

export default function AdminProjects() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminProject[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [archived, setArchived] = useState<boolean | undefined>(undefined)

  async function load(p = 1, s = search, a = archived) {
    try {
      const r = await api.adminListProjects({ search: s, archived: a, page: p })
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
    { key: "name", title: "项目", render: (p) => <><div>{p.name}</div><div className="muted" style={{ fontSize: 12 }}>{p.slug}</div></> },
    { key: "org", title: "工作组", render: (p) => p.org.name },
    { key: "runs", title: "运行", num: true, render: (p) => p._count.runs },
    { key: "keys", title: "API Key", num: true, render: (p) => p._count.apiKeys },
    { key: "status", title: "状态", render: (p) => <Badge variant={p.archivedAt ? "neutral" : "success"}>{p.archivedAt ? "已归档" : "活跃"}</Badge> },
    { key: "created", title: "创建", render: (p) => timeAgo(p.createdAt) },
    { key: "go", title: "", render: (p) => <Link className="btn btn-sm" to={`/project/${p.id}`}>查看</Link> },
  ]

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>项目管理</h1>
          <div className="sub">共 {total} 个项目（跨所有工作组）</div>
        </div>
      </div>
      <div className="card r-2">
        <div className="card-body">
          <Field label="筛选">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="名称 / slug" style={{ flex: 1 }} onKeyDown={(e) => e.key === "Enter" && load(1)} />
              <select className="input" value={archived === undefined ? "" : String(archived)} onChange={(e) => { const v = e.target.value; setArchived(v === "" ? undefined : v === "true") }}>
                <option value="">全部</option>
                <option value="false">活跃</option>
                <option value="true">已归档</option>
              </select>
              <Button onClick={() => load(1)}>筛选</Button>
            </div>
          </Field>
          <DataTable columns={columns} rows={rows} rowKey={(p) => p.id} pageSize={20} />
          <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
        </div>
      </div>
    </div>
  )
}
