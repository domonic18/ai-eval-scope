/** 超管后台 · 用户管理：列表 / 搜索 / 编辑（姓名/角色/状态）/ 删除。 */
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/shadcn/select"
import { useToast } from "../../components/toast"
import { DataTable, PageHead, Pager, StatusBadge, type Column } from "../../components/shared"
import { timeAgo } from "../../lib/format"
import { loadSession } from "../../store/auth"
import { useDebouncedValue } from "../../lib/useDebounce"

export default function AdminUsers() {
  const toast = useToast()
  const selfId = loadSession()?.user?.id
  const [rows, setRows] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const debouncedSearch = useDebouncedValue(search, 300)
  const [editing, setEditing] = useState<AdminUser | null>(null)
  const [form, setForm] = useState({ name: "", role: "user", status: "active" })
  const [delTarget, setDelTarget] = useState<AdminUser | null>(null)
  const [busy, setBusy] = useState(false)

  async function load(p = 1) {
    try {
      const r = await api.adminListUsers({ search: debouncedSearch || undefined, page: p })
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
  }, [debouncedSearch])

  function openEdit(u: AdminUser) {
    setEditing(u)
    setForm({ name: u.name || "", role: u.role, status: u.status })
  }

  // 编辑自己时，若降权或禁用 → 禁止提交（后端 SELF_LOCKOUT 兜底）
  const selfLock =
    !!editing && editing.id === selfId && (form.role === "user" || form.status === "disabled")

  async function submitEdit() {
    if (!editing || selfLock) return
    setBusy(true)
    try {
      await api.adminUpdateUser(editing.id, {
        name: form.name.trim() === "" ? null : form.name.trim(),
        role: form.role,
        status: form.status,
      })
      toast.success("已保存")
      setEditing(null)
      await load()
    } catch (e) {
      const code = (e as { response?: { data?: { code?: string } } }).response?.data?.code
      toast.error(code === "SELF_LOCKOUT" ? "不能降权/禁用自己" : "保存失败")
    } finally {
      setBusy(false)
    }
  }

  async function confirmDelete() {
    if (!delTarget) return
    setBusy(true)
    try {
      await api.adminDeleteUser(delTarget.id)
      toast.success("已删除")
      setDelTarget(null)
      await load()
    } catch (e) {
      const code = (e as { response?: { data?: { code?: string } } }).response?.data?.code
      toast.error(code === "SELF_LOCKOUT" ? "不能删除自己" : "删除失败")
    } finally {
      setBusy(false)
    }
  }

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
          <Button variant="outline" size="sm" onClick={() => openEdit(u)}>
            编辑
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-red-400"
            onClick={() => setDelTarget(u)}
            disabled={u.id === selfId}
          >
            删除
          </Button>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6 p-6">
      <PageHead title="用户管理" sub={`共 ${total} 个账号`} />
      <div className="space-y-3 rounded-lg border bg-card p-4 text-card-foreground">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索邮箱 / 姓名"
        />
        <DataTable columns={columns} rows={rows} rowKey={(u) => u.id} />
        <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
      </div>

      {/* 编辑对话框 */}
      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑用户</DialogTitle>
            <DialogDescription>修改用户姓名、角色与状态。</DialogDescription>
          </DialogHeader>
          {editing && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <label className="text-sm font-medium">邮箱</label>
                <Input value={editing.email} disabled />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">姓名</label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="（可选）"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">角色</label>
                  <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="user">user</SelectItem>
                      <SelectItem value="admin">admin</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">状态</label>
                  <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="active">active</SelectItem>
                      <SelectItem value="disabled">disabled</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              {selfLock && (
                <p className="text-xs text-red-400">不能将自己降权或禁用。</p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>
              取消
            </Button>
            <Button onClick={submitEdit} disabled={busy || selfLock}>
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <Dialog open={!!delTarget} onOpenChange={(o) => !o && setDelTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除用户</DialogTitle>
            <DialogDescription>
              确认删除用户 <strong>{delTarget?.email}</strong>？其团队成员关系与加入申请将一并清除，此操作不可撤销。
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
    </div>
  )
}
