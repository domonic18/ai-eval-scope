/** 超管后台 · 工作组（组织）管理：列表 + 删除（级联）。 */
import { useEffect, useState } from "react"
import { api, type AdminOrg } from "../../api/client"
import { Button, Callout, DataTable, Modal, useToast, type Column } from "../../components/ui"
import { timeAgo } from "../../lib/format"
import { Pager } from "./AdminUsers"

export default function AdminOrgs() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminOrg[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [del, setDel] = useState<AdminOrg | null>(null)

  async function load(p = 1) {
    try {
      const r = await api.adminListOrgs({ page: p })
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
    } catch {
      toast.error("加载工作组失败")
    }
  }
  useEffect(() => {
    load()
  }, [])
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
    { key: "name", title: "工作组", render: (o) => <><div>{o.name}</div><div className="muted" style={{ fontSize: 12 }}>{o.slug}</div></> },
    { key: "members", title: "成员", num: true, render: (o) => o.memberCount },
    { key: "projects", title: "项目", num: true, render: (o) => o.projectCount },
    { key: "runs", title: "运行", num: true, render: (o) => o.runCount },
    { key: "created", title: "创建", render: (o) => timeAgo(o.createdAt) },
    {
      key: "actions",
      title: "操作",
      render: (o) => (
        <Button size="sm" variant="danger" onClick={() => setDel(o)}>删除</Button>
      ),
    },
  ]

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>工作组管理</h1>
          <div className="sub">共 {total} 个工作组（删除将级联清除其项目 / 运行 / 制品）</div>
        </div>
      </div>
      <div className="card r-2">
        <div className="card-body">
          <DataTable columns={columns} rows={rows} rowKey={(o) => o.id} pageSize={20} />
          <Pager page={page} total={total} onPrev={() => load(page - 1)} onNext={() => load(page + 1)} />
        </div>
      </div>
      <Modal
        open={!!del}
        onClose={() => setDel(null)}
        title="删除工作组"
        footer={<><Button onClick={() => setDel(null)}>取消</Button><Button variant="danger" onClick={confirmDelete}>确认删除</Button></>}
      >
        {del && (
          <Callout variant="warn">
            将删除工作组 <strong>{del.name}</strong> 及其 <strong>{del.projectCount}</strong> 个项目、<strong>{del.runCount}</strong> 次运行及全部制品。此操作不可恢复。
          </Callout>
        )}
      </Modal>
    </div>
  )
}
