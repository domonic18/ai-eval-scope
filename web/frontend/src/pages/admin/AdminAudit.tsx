/** 超管后台 · 审计日志：全平台敏感操作流水。 */
import { useEffect, useState } from "react"
import { api, type AdminAuditRow } from "../../api/client"
import { Badge, Button, DataTable, Field, Input, useToast, type Column } from "../../components/ui"
import { timeAgo } from "../../lib/format"
import { Pager } from "./AdminUsers"

export default function AdminAudit() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminAuditRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [action, setAction] = useState("")

  async function load(p = 1) {
    try {
      const r = await api.adminListAudit({ action: action || undefined, page: p })
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
    } catch {
      toast.error("加载审计失败")
    }
  }
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const columns: Column<AdminAuditRow>[] = [
    { key: "action", title: "操作", render: (a) => <Badge variant="neutral">{a.action}</Badge> },
    { key: "actor", title: "操作者", render: (a) => <span className="mono" style={{ fontSize: 12 }}>{a.actorUserId?.slice(0, 13) ?? "system"}…</span> },
    { key: "target", title: "对象", render: (a) => <span className="muted" style={{ fontSize: 12 }}>{a.targetType ?? "—"}{a.targetId ? ` · ${a.targetId.slice(0, 8)}…` : ""}</span> },
    { key: "org", title: "工作组", render: (a) => (a.orgId ? <span className="mono" style={{ fontSize: 11 }}>{a.orgId.slice(0, 8)}…</span> : <Badge variant="accent">platform</Badge>) },
    { key: "time", title: "时间", render: (a) => timeAgo(a.createdAt) },
  ]

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>审计日志</h1>
          <div className="sub">共 {total} 条（全平台，含平台级操作 orgId=platform）</div>
        </div>
      </div>
      <div className="card r-2">
        <div className="card-body">
          <Field label="按操作过滤">
            <div style={{ display: "flex", gap: 8 }}>
              <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder="如 user.update / key.create" style={{ flex: 1 }} onKeyDown={(e) => e.key === "Enter" && load(1)} />
              <Button onClick={() => load(1)}>筛选</Button>
            </div>
          </Field>
          <DataTable columns={columns} rows={rows} rowKey={(a) => a.id} pageSize={20} />
          <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
        </div>
      </div>
    </div>
  )
}
