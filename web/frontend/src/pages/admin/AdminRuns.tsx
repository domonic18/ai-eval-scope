/** 超管后台 · 评估任务：全平台 run 列表 + 状态过滤 + 指标。 */
import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api, type AdminRun } from "../../api/client"
import { Badge, Button, DataTable, Field, Input, useToast, type Column } from "../../components/ui"
import { fmt3, timeAgo } from "../../lib/format"
import { Pager } from "./AdminUsers"

const STATUSES = ["", "completed", "failed", "running", "partial"]

export default function AdminRuns() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminRun[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState("")
  const [search, setSearch] = useState("")

  async function load(p = 1) {
    try {
      const r = await api.adminListRuns({ status: status || undefined, search: search || undefined, page: p })
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
    } catch {
      toast.error("加载运行失败")
    }
  }
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const statusVariant = (s: string): "success" | "danger" | "info" | "neutral" =>
    s === "completed" ? "success" : s === "failed" ? "danger" : s === "running" ? "info" : "neutral"

  const columns: Column<AdminRun>[] = [
    { key: "run", title: "运行", render: (r) => <Link to={`/run/${r.externalRunId}`} className="mono" style={{ fontSize: 12 }}>{r.externalRunId}</Link> },
    { key: "project", title: "项目 / 工作组", render: (r) => <><div>{r.project.name}</div><div className="muted" style={{ fontSize: 12 }}>{r.project.org.name}</div></> },
    { key: "status", title: "状态", render: (r) => <Badge variant={statusVariant(r.status)}>{r.status}</Badge> },
    { key: "dr", title: "DR", num: true, render: (r) => fmt3(r.dr) },
    { key: "cpr", title: "CPR", num: true, render: (r) => fmt3(r.cpr) },
    { key: "reward", title: "Reward", num: true, render: (r) => fmt3(r.avgReward) },
    { key: "samples", title: "样本", num: true, render: (r) => r.totalSamples },
    { key: "created", title: "时间", render: (r) => timeAgo(r.createdAt) },
  ]

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>评估任务</h1>
          <div className="sub">共 {total} 次运行（全平台）</div>
        </div>
      </div>
      <div className="card r-2">
        <div className="card-body">
          <Field label="筛选">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
                {STATUSES.map((s) => <option key={s} value={s}>{s || "全部状态"}</option>)}
              </select>
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="按项目名搜索" style={{ flex: 1 }} onKeyDown={(e) => e.key === "Enter" && load(1)} />
              <Button onClick={() => load(1)}>筛选</Button>
            </div>
          </Field>
          <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} pageSize={20} />
          <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
        </div>
      </div>
    </div>
  )
}
