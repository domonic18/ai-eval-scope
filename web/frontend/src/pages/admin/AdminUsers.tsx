/** 超管后台 · 用户管理：列表 / 搜索 / 提降权 / 启用禁用。 */
import { useEffect, useState } from "react"
import { api, type AdminUser } from "../../api/client"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import { useToast } from "../../components/toast"
import { DataTable, PageHead, Pager, StatusBadge, type Column } from "../../components/shared"
import { timeAgo } from "../../lib/format"
import { loadSession } from "../../store/auth"

export default function AdminUsers() {
  const toast = useToast()
  const selfId = loadSession()?.user?.id
  const [rows, setRows] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [target, setTarget] = useState<AdminUser | null>(null)
  const [action, setAction] = useState<"promote" | "demote" | "enable" | "disable" | null>(null)

  async function load(p = page, s = search) {
    try {
      const r = await api.adminListUsers({ search: s, page: p })
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
    } catch {
      toast.error("加载用户失败")
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
      const code = (e as { response?: { data?: { code?: string } } }).response?.data?.code
      toast.error(code === "SELF_LOCKOUT" ? "不能降权/禁用自己" : "操作失败")
    }
  }

  const actionLabel =
    action === "promote"
      ? "提升为超级管理员"
      : action === "demote"
        ? "降为普通用户"
        : action === "disable"
          ? "禁用账号"
          : "启用账号"

  const columns: Column<AdminUser>[] = [
    {
      key: "email",
      title: "邮箱",
      render: (u) => (
        <div>
          <div>{u.email}</div>
          <div className="text-xs text-muted-foreground">{u.name || "—"}</div>
        </div>
      ),
    },
    {
      key: "role",
      title: "角色",
      render: (u) =>
        u.role === "admin" ? (
          <span className="inline-flex items-center rounded-md border border-primary/40 px-2 py-0.5 text-xs font-medium text-primary">
            admin
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">user</span>
        ),
    },
    { key: "status", title: "状态", render: (u) => <StatusBadge status={u.status} /> },
    { key: "memberships", title: "团队", num: true, render: (u) => u._count?.memberships ?? 0 },
    { key: "created", title: "注册", render: (u) => timeAgo(u.createdAt) },
    {
      key: "actions",
      title: "操作",
      render: (u) => (
        <div className="flex gap-2">
          {u.role === "admin" ? (
            <Button variant="outline" size="sm" onClick={() => open(u, "demote")} disabled={u.id === selfId}>
              降为用户
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={() => open(u, "promote")}>
              提为超管
            </Button>
          )}
          {u.status === "active" ? (
            <Button variant="outline" size="sm" onClick={() => open(u, "disable")} disabled={u.id === selfId}>
              禁用
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={() => open(u, "enable")}>
              启用
            </Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6 p-6">
      <PageHead title="用户管理" sub={`共 ${total} 个账号`} />
      <div className="space-y-3 rounded-lg border bg-card p-4 text-card-foreground">
        <div className="flex gap-2">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索邮箱 / 姓名（回车）"
            onKeyDown={(e) => e.key === "Enter" && load(1, search)}
          />
          <Button onClick={() => load(1, search)}>搜索</Button>
        </div>
        <DataTable columns={columns} rows={rows} rowKey={(u) => u.id} />
        <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
      </div>

      <Dialog open={!!target} onOpenChange={(o) => !o && setTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{actionLabel}</DialogTitle>
            <DialogDescription>
              {target && (
                <span className="text-foreground">
                  确认对 <strong>{target.email}</strong> 执行「{actionLabel}」？
                  {action === "disable" && (
                    <span className="mt-1 block text-muted-foreground">
                      禁用后该用户无法登录，已签发的 token 也在下次请求被拒绝。
                    </span>
                  )}
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTarget(null)}>
              取消
            </Button>
            <Button
              variant={action === "disable" || action === "demote" ? "destructive" : "default"}
              onClick={confirm}
            >
              确认
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
