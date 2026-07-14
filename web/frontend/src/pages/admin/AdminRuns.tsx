/** 超管后台 · 评估任务：全平台 run 列表 + 状态过滤 + 指标 + 删除。 */
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import { useToast } from "../../components/toast"
import { DataTable, Page, PageHead, Pager, StatusBadge, type Column } from "../../components/shared"
import { fmt3, timeAgo } from "../../lib/format"
import { useDebouncedValue } from "../../lib/useDebounce"
import { useScenarioDefaults } from "../../hooks/useScenarioDefaults"

const STATUSES = ["all", "completed", "failed", "running", "partial"]

export default function AdminRuns() {
  const toast = useToast()
  // #65：指标列从 defaultDefs 动态生成（零 courseware:* 硬编码）
  const defaultDefs = useScenarioDefaults()
  const [rows, setRows] = useState<AdminRun[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState("all")
  const [search, setSearch] = useState("")
  const debouncedSearch = useDebouncedValue(search, 300)
  const [delTarget, setDelTarget] = useState<AdminRun | null>(null)
  const [busy, setBusy] = useState(false)

  async function load(p = 1) {
    try {
      const r = await api.adminListRuns({
        status: status === "all" ? undefined : status,
        search: debouncedSearch || undefined,
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
    load(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch, status])

  async function confirmDelete() {
    if (!delTarget) return
    setBusy(true)
    try {
      await api.adminDeleteRun(delTarget.id)
      toast.success("已删除")
      setDelTarget(null)
      await load()
    } catch {
      toast.error("删除失败")
    } finally {
      setBusy(false)
    }
  }

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
    // #65：指标列从 defaultDefs 动态生成（有阈值的指标）
    ...defaultDefs
      .filter((d) => d.threshold != null)
      .map((d) => ({
        key: d.id,
        title: d.name ?? d.id,
        num: true as const,
        render: (r: AdminRun) => fmt3(r.metrics?.[d.id]),
      })),
    { key: "samples", title: "样本", num: true, render: (r) => r.totalSamples },
    { key: "created", title: "时间", render: (r) => timeAgo(r.createdAt) },
    {
      key: "actions",
      title: "操作",
      render: (r) => (
        <Button
          variant="outline"
          size="sm"
          className="text-red-400"
          onClick={() => setDelTarget(r)}
        >
          删除
        </Button>
      ),
    },
  ]

  return (
    <Page>
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
          />
        </div>
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
        <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
      </div>

      <Dialog open={!!delTarget} onOpenChange={(o) => !o && setDelTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除运行</DialogTitle>
            <DialogDescription>
              确认删除运行 <strong>{delTarget?.externalRunId}</strong>？其下所有样本、产出物与评估记录将一并级联删除，此操作不可撤销。
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
