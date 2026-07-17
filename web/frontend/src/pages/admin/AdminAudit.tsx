/** 超管后台 · 审计日志：全平台敏感操作流水。 */
import { useEffect, useState } from "react"
import { api, type AdminAuditRow } from "../../api/client"
import { Input } from "@/components/shadcn/input"
import { useToast } from "../../hooks/useToast"
import { DataTable, Page, PageHead, Pager, type Column } from "../../components/shared"
import { timeAgo } from "../../lib/format"
import { useDebouncedValue } from "../../lib/useDebounce"

export default function AdminAudit() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminAuditRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [action, setAction] = useState("")
  const debouncedAction = useDebouncedValue(action, 300)

  async function load(p = 1) {
    try {
      const r = await api.adminListAudit({ action: debouncedAction || undefined, page: p })
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
    } catch {
      toast.error("加载审计失败")
    }
  }
  useEffect(() => {
    load(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedAction])

  const columns: Column<AdminAuditRow>[] = [
    {
      key: "action",
      title: "操作",
      render: (a) => (
        <span className="inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-xs">
          {a.action}
        </span>
      ),
    },
    {
      key: "actor",
      title: "操作者",
      render: (a) => (
        <span className="font-mono text-xs text-muted-foreground">
          {(a.actorUserId ?? "system").slice(0, 13)}…
        </span>
      ),
    },
    {
      key: "target",
      title: "对象",
      render: (a) => (
        <span className="text-xs text-muted-foreground">
          {a.targetType ?? "—"}
          {a.targetId ? ` · ${a.targetId.slice(0, 8)}…` : ""}
        </span>
      ),
    },
    {
      key: "org",
      title: "工作组",
      render: (a) =>
        a.orgId ? (
          <span className="font-mono text-xs text-muted-foreground">{a.orgId.slice(0, 8)}…</span>
        ) : (
          <span className="inline-flex items-center rounded-md border border-primary/40 px-2 py-0.5 text-xs font-medium text-primary">
            platform
          </span>
        ),
    },
    { key: "time", title: "时间", render: (a) => timeAgo(a.createdAt) },
  ]

  return (
    <Page>
      <PageHead title="审计日志" sub={`共 ${total} 条（全平台，含平台级操作 orgId=platform）`} />
      <div className="space-y-3 rounded-lg border bg-card p-4 text-card-foreground">
        <Input
          value={action}
          onChange={(e) => setAction(e.target.value)}
          placeholder="按操作过滤，如 user.update / key.create / artifact.delete"
        />
        <DataTable columns={columns} rows={rows} rowKey={(a) => a.id} />
        <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
      </div>
    </Page>
  )
}
