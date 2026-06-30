/** 超管后台 · 评估任务：全平台 run 列表 + 状态过滤 + 指标。 */
import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api, type AdminRun } from "../../api/client"
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
import { DataTable, PageHead, Pager, StatusBadge, type Column } from "../../components/shared"
import { fmt3, timeAgo } from "../../lib/format"

const STATUSES = ["all", "completed", "failed", "running", "partial"]

export default function AdminRuns() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminRun[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState("all")
  const [search, setSearch] = useState("")

  async function load(p = 1) {
    try {
      const r = await api.adminListRuns({
        status: status === "all" ? undefined : status,
        search: search || undefined,
        page: p,
      })
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

  const columns: Column<AdminRun>[] = [
    {
      key: "run",
      title: "运行",
      render: (r) => (
        <Link to={`/run/${r.externalRunId}`} className="font-mono text-xs hover:text-primary">
          {r.externalRunId}
        </Link>
      ),
    },
    {
      key: "project",
      title: "项目 / 工作组",
      render: (r) => (
        <div>
          <div>{r.project.name}</div>
          <div className="text-xs text-muted-foreground">{r.project.org.name}</div>
        </div>
      ),
    },
    { key: "status", title: "状态", render: (r) => <StatusBadge status={r.status} /> },
    { key: "dr", title: "DR", num: true, render: (r) => fmt3(r.dr) },
    { key: "cpr", title: "CPR", num: true, render: (r) => fmt3(r.cpr) },
    { key: "reward", title: "Reward", num: true, render: (r) => fmt3(r.avgReward) },
    { key: "samples", title: "样本", num: true, render: (r) => r.totalSamples },
    { key: "created", title: "时间", render: (r) => timeAgo(r.createdAt) },
  ]

  return (
    <div className="space-y-6 p-6">
      <PageHead title="评估任务" sub={`共 ${total} 次运行（全平台）`} />
      <div className="space-y-3 rounded-lg border bg-card p-4 text-card-foreground">
        <div className="flex gap-2">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="全部状态" />
            </SelectTrigger>
            <SelectContent>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {s === "all" ? "全部状态" : s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="按项目名搜索"
            onKeyDown={(e) => e.key === "Enter" && load(1)}
          />
          <Button onClick={() => load(1)}>筛选</Button>
        </div>
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
        <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
      </div>
    </div>
  )
}
