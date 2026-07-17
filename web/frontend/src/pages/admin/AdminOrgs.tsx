/** 超管后台 · 工作组（组织）管理：列表 + 删除（级联）。 */
import { useCallback, useEffect, useState } from "react"
import { api, type AdminOrg } from "../../api/client"
import { Button } from "@/components/shadcn/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import { useToast } from "../../hooks/useToast"
import { DataTable, Page, PageHead, Pager, type Column } from "../../components/shared"
import { timeAgo } from "../../lib/format"

export default function AdminOrgs() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminOrg[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [del, setDel] = useState<AdminOrg | null>(null)

  const load = useCallback(async (p = 1) => {
    try {
      const r = await api.adminListOrgs({ page: p })
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
    } catch {
      toast.error("加载工作组失败")
    }
  }, [toast])

  useEffect(() => {
    load()
  }, [load])

  async function confirmDelete() {
    if (!del) return
    try {
      await api.adminDeleteOrg(del.id)
      toast.success("已删除")
      setDel(null)
      await load(page)
    } catch {
      toast.error("删除失败")
    }
  }

  const columns: Column<AdminOrg>[] = [
    {
      key: "name",
      title: "工作组",
      render: (o) => (
        <div>
          <div>{o.name}</div>
          <div className="text-xs text-muted-foreground">{o.slug}</div>
        </div>
      ),
    },
    { key: "members", title: "成员", num: true, render: (o) => o.memberCount },
    { key: "projects", title: "项目", num: true, render: (o) => o.projectCount },
    { key: "runs", title: "运行", num: true, render: (o) => o.runCount },
    { key: "created", title: "创建", render: (o) => timeAgo(o.createdAt) },
    {
      key: "actions",
      title: "操作",
      render: (o) => (
        <Button variant="outline" size="sm" className="text-red-400" onClick={() => setDel(o)}>
          删除
        </Button>
      ),
    },
  ]

  return (
    <Page>
      <PageHead title="工作组管理" sub={`共 ${total} 个工作组（删除将级联清除其项目 / 运行 / 制品）`} />
      <div className="space-y-3 rounded-lg border bg-card p-4 text-card-foreground">
        <DataTable columns={columns} rows={rows} rowKey={(o) => o.id} />
        <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
      </div>

      <Dialog open={!!del} onOpenChange={(o) => !o && setDel(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除工作组</DialogTitle>
            <DialogDescription>
              {del && (
                <span className="text-foreground">
                  将删除工作组 <strong>{del.name}</strong> 及其 <strong>{del.projectCount}</strong> 个项目、
                  <strong>{del.runCount}</strong> 次运行及全部制品。此操作不可恢复。
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDel(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  )
}
