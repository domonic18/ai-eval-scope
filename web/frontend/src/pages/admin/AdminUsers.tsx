/** 超管后台 · 用户管理：列表 / 搜索 / 提降权 / 启用禁用。 */
import { useEffect, useState } from "react"
import { api, type AdminUser } from "../../api/client"
import { Badge, Button, Callout, DataTable, Field, Input, Modal, type Column } from "../../components/ui"
import { useToast } from "../../components/ui"
import { timeAgo } from "../../lib/format"
import { loadSession } from "../../store/auth"

export default function AdminUsers() {
  const toast = useToast()
  const selfId = loadSession()?.user?.id
  const [rows, setRows] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(false)
  const [target, setTarget] = useState<AdminUser | null>(null)
  const [action, setAction] = useState<"promote" | "demote" | "enable" | "disable" | null>(null)

  async function load(p = page, s = search) {
    setLoading(true)
    try {
      const r = await api.adminListUsers({ search: s, page: p })
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
    } catch {
      toast.error("加载用户失败")
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function open(u: AdminUser, act: typeof action) {
    setTarget(u)
    setAction(act)
  }
  async function confirm() {
    if (!target || !action) return
    const data: { role?: string; status?: string } = {}
    if (action === "promote") data.role = "admin"
    if (action === "demote") data.role = "user"
    if (action === "enable") data.status = "active"
    if (action === "disable") data.status = "disabled"
    try {
      await api.adminUpdateUser(target.id, data)
      toast.success("已更新")
      setTarget(null)
      setAction(null)
      await load()
    } catch (e) {
      const msg = (e as { response?: { data?: { code?: string; error?: string } } }).response?.data
      toast.error(msg?.code === "SELF_LOCKOUT" ? "不能降权/禁用自己" : msg?.error || "操作失败")
    }
  }

  const columns: Column<AdminUser>[] = [
    { key: "email", title: "邮箱", render: (u) => <><div>{u.email}</div><div className="muted" style={{ fontSize: 12 }}>{u.name || "—"}</div></> },
    { key: "role", title: "角色", render: (u) => <Badge variant={u.role === "admin" ? "accent" : "neutral"}>{u.role}</Badge> },
    { key: "status", title: "状态", render: (u) => <Badge variant={u.status === "active" ? "success" : "danger"}>{u.status}</Badge> },
    { key: "memberships", title: "所属团队", num: true, render: (u) => u._count?.memberships ?? 0 },
    { key: "created", title: "注册", render: (u) => timeAgo(u.createdAt) },
    {
      key: "actions",
      title: "操作",
      render: (u) => (
        <div style={{ display: "flex", gap: 6 }}>
          {u.role === "admin" ? (
            <Button size="sm" onClick={() => open(u, "demote")} disabled={u.id === selfId}>降为用户</Button>
          ) : (
            <Button size="sm" onClick={() => open(u, "promote")}>提为超管</Button>
          )}
          {u.status === "active" ? (
            <Button size="sm" onClick={() => open(u, "disable")} disabled={u.id === selfId}>禁用</Button>
          ) : (
            <Button size="sm" onClick={() => open(u, "enable")}>启用</Button>
          )}
        </div>
      ),
    },
  ]

  const actionLabel =
    action === "promote" ? "提升为超级管理员" :
    action === "demote" ? "降为普通用户" :
    action === "disable" ? "禁用账号" : "启用账号"

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>用户管理</h1>
          <div className="sub">共 {total} 个账号</div>
        </div>
      </div>
      <div className="card r-2">
        <div className="card-body">
          <Field label="搜索（邮箱 / 姓名）">
            <div style={{ display: "flex", gap: 8 }}>
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="回车搜索" style={{ flex: 1 }} onKeyDown={(e) => e.key === "Enter" && load(1, search)} />
              <Button onClick={() => load(1, search)}>搜索</Button>
            </div>
          </Field>
          <DataTable columns={columns} rows={rows} rowKey={(u) => u.id} pageSize={20} />
          <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} loading={loading} />
        </div>
      </div>

      <Modal
        open={!!target}
        onClose={() => setTarget(null)}
        title={actionLabel}
        footer={<><Button onClick={() => setTarget(null)}>取消</Button><Button variant="primary" onClick={confirm}>确认</Button></>}
      >
        {target && (
          <Callout variant="warn">
            确认对 <strong>{target.email}</strong> 执行「{actionLabel}」？
            {action === "disable" && <div className="muted" style={{ marginTop: 6 }}>禁用后该用户无法登录，已签发的 token 也在下次请求被拒绝。</div>}
          </Callout>
        )}
      </Modal>
    </div>
  )
}

export function Pager({ page, total, onPrev, onNext, loading }: { page: number; total: number; onPrev: () => void; onNext: () => void; loading?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 12, marginTop: 12, fontSize: 13, color: "var(--text-secondary)" }}>
      <span>第 {page} 页 · 共 {total}</span>
      <Button size="sm" onClick={onPrev} disabled={page <= 1 || loading}>上一页</Button>
      <Button size="sm" onClick={onNext} disabled={total <= page * 50 || loading}>下一页</Button>
    </div>
  )
}
