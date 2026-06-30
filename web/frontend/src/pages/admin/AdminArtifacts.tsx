/** 超管后台 · 产出物（制品）管理：列表 + kind 过滤 + 存储用量。 */
import { useEffect, useState } from "react"
import { api, type AdminArtifact } from "../../api/client"
import { Button } from "@/components/shadcn/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/shadcn/select"
import { useToast } from "../../components/toast"
import { DataTable, PageHead, Pager, StatCard, type Column } from "../../components/shared"
import { fmtBytes, timeAgo } from "../../lib/format"

const KINDS = ["all", "output", "screenshot", "judge_record", "trace", "manifest"]

export default function AdminArtifacts() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminArtifact[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [kind, setKind] = useState("all")
  const [storage, setStorage] = useState(0)

  async function load(p = 1) {
    try {
      const [r, ov] = await Promise.all([
        api.adminListArtifacts({ kind: kind === "all" ? undefined : kind, page: p }),
        api.adminOverview(),
      ])
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
      setStorage(ov.artifacts.storageBytes)
    } catch {
      toast.error("加载产出物失败")
    }
  }
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const columns: Column<AdminArtifact>[] = [
    {
      key: "name",
      title: "制品",
      render: (a) => (
        <div>
          <div>{a.originalName || a.kind}</div>
          <div className="font-mono text-xs text-muted-foreground">{a.run.externalRunId}</div>
        </div>
      ),
    },
    {
      key: "kind",
      title: "类型",
      render: (a) => (
        <span className="inline-flex items-center rounded-md border border-sky-500/40 px-2 py-0.5 text-xs font-medium text-sky-400">
          {a.kind}
        </span>
      ),
    },
    { key: "project", title: "项目", render: (a) => a.project.name },
    { key: "size", title: "大小", num: true, render: (a) => fmtBytes(a.sizeBytes) },
    {
      key: "ct",
      title: "Content-Type",
      render: (a) => <span className="text-xs text-muted-foreground">{a.contentType}</span>,
    },
    { key: "created", title: "时间", render: (a) => timeAgo(a.createdAt) },
  ]

  return (
    <div className="space-y-6 p-6">
      <PageHead title="产出物管理" sub="全平台评估制品（output / screenshot / judge_record / trace / manifest）" />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        <StatCard label="制品总数" value={String(total)} />
        <StatCard label="存储用量" value={fmtBytes(storage)} />
      </div>
      <div className="space-y-3 rounded-lg border bg-card p-4 text-card-foreground">
        <div className="flex gap-2">
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger className="w-40">
              <SelectValue placeholder="全部类型" />
            </SelectTrigger>
            <SelectContent>
              {KINDS.map((k) => (
                <SelectItem key={k} value={k}>
                  {k === "all" ? "全部类型" : k}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button onClick={() => load(1)}>筛选</Button>
        </div>
        <DataTable columns={columns} rows={rows} rowKey={(a) => a.id} />
        <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
      </div>
    </div>
  )
}
