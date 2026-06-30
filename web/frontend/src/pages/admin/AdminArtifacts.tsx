/** 超管后台 · 产出物（制品）管理：列表 + kind 过滤 + 存储用量。 */
import { useEffect, useState } from "react"
import { api, type AdminArtifact } from "../../api/client"
import { Badge, Button, DataTable, Field, Metric, useToast, type Column } from "../../components/ui"
import { fmtBytes, timeAgo } from "../../lib/format"
import { Pager } from "./AdminUsers"

const KINDS = ["", "output", "screenshot", "judge_record", "trace", "manifest"]

export default function AdminArtifacts() {
  const toast = useToast()
  const [rows, setRows] = useState<AdminArtifact[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [kind, setKind] = useState("")
  const [storage, setStorage] = useState(0)

  async function load(p = 1) {
    try {
      const r = await api.adminListArtifacts({ kind: kind || undefined, page: p })
      setRows(r.items)
      setTotal(r.total)
      setPage(r.page)
      const ov = await api.adminOverview()
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
    { key: "name", title: "制品", render: (a) => <><div>{a.originalName || a.kind}</div><div className="muted mono" style={{ fontSize: 11 }}>{a.run.externalRunId}</div></> },
    { key: "kind", title: "类型", render: (a) => <Badge variant="info">{a.kind}</Badge> },
    { key: "project", title: "项目", render: (a) => a.project.name },
    { key: "size", title: "大小", num: true, render: (a) => fmtBytes(a.sizeBytes) },
    { key: "ct", title: "Content-Type", render: (a) => <span className="muted" style={{ fontSize: 12 }}>{a.contentType}</span> },
    { key: "created", title: "时间", render: (a) => timeAgo(a.createdAt) },
  ]

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>产出物管理</h1>
          <div className="sub">全平台评估制品（output / screenshot / judge_record / trace / manifest）</div>
        </div>
      </div>
      <div className="card r-2">
        <div className="card-body">
          <div style={{ display: "flex", gap: 16, marginBottom: 16, flexWrap: "wrap" }}>
            <Metric label="制品总数" value={String(total)} />
            <Metric label="存储用量" value={fmtBytes(storage)} />
          </div>
          <Field label="按类型筛选">
            <div style={{ display: "flex", gap: 8 }}>
              <select className="input" value={kind} onChange={(e) => setKind(e.target.value)} style={{ flex: 1 }}>
                {KINDS.map((k) => <option key={k} value={k}>{k || "全部类型"}</option>)}
              </select>
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
