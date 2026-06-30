/** 超管后台 · 总览：全平台计数 + run 指标趋势 + score 分布。 */
import { useEffect, useState } from "react"
import { api } from "../../api/client"
import { Metric, LineChart, Callout, Badge } from "../../components/ui"
import { num, fmtBytes } from "../../lib/format"

interface Overview {
  users: { total: number; active: number; disabled: number; admins: number }
  orgs: number
  projects: { total: number; archived: number }
  runs: { total: number; completed: number; failed: number; pending: number }
  samples: number
  artifacts: { total: number; storageBytes: number }
}

export default function AdminOverview() {
  const [ov, setOv] = useState<Overview | null>(null)
  const [trends, setTrends] = useState<{ DR: number; CPR: number; Reward: number }[]>([])
  const [dist, setDist] = useState<{ bucket: string; count: number }[]>([])
  const [err, setErr] = useState("")

  useEffect(() => {
    Promise.all([api.adminOverview(), api.adminTrends(100), api.adminScoreDistribution()])
      .then(([o, t, d]) => {
        setOv(o)
        setTrends(t)
        setDist(d)
      })
      .catch((e) => setErr((e as Error).message))
  }, [])

  if (err) return <Callout variant="warn">加载失败：{err}</Callout>
  if (!ov) return <div className="page" style={{ padding: 32, color: "var(--text-secondary)" }}>加载中…</div>

  const drSeries = [{ name: "DR", color: "var(--signal)", data: trends.map((t) => t.DR) }]
  const rewardSeries = [{ name: "Reward", color: "var(--accent)", data: trends.map((t) => t.Reward) }]
  const distMax = Math.max(1, ...dist.map((d) => d.count))

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>
            平台总览 <Badge variant="accent">super admin</Badge>
          </h1>
          <div className="sub">全平台用户 / 工作组 / 项目 / 评估任务 / 产出物 统计</div>
        </div>
      </div>

      <div className="card r-2">
        <div className="card-head">
          <h3>规模</h3>
        </div>
        <div className="card-body">
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <Metric label="用户" value={num(ov.users.total)} foot={`活跃 ${ov.users.active} · 禁用 ${ov.users.disabled} · 超管 ${ov.users.admins}`} />
            <Metric label="工作组" value={num(ov.orgs)} />
            <Metric label="项目" value={num(ov.projects.total)} foot={`归档 ${ov.projects.archived}`} />
            <Metric label="评估任务" value={num(ov.runs.total)} foot={`完成 ${ov.runs.completed} · 失败 ${ov.runs.failed} · 进行 ${ov.runs.pending}`} />
            <Metric label="样本" value={num(ov.samples)} />
            <Metric label="产出物" value={num(ov.artifacts.total)} foot={fmtBytes(ov.artifacts.storageBytes)} />
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }} className="r-2">
        <div className="card">
          <div className="card-head">
            <h3>DR 趋势（最近 {trends.length} 次运行）</h3>
          </div>
          <div className="card-body">
            {trends.length > 0 ? <LineChart series={drSeries} /> : <div className="muted">暂无数据</div>}
          </div>
        </div>
        <div className="card">
          <div className="card-head">
            <h3>Reward 趋势</h3>
          </div>
          <div className="card-body">
            {trends.length > 0 ? <LineChart series={rewardSeries} /> : <div className="muted">暂无数据</div>}
          </div>
        </div>
      </div>

      <div className="card r-2">
        <div className="card-head">
          <h3>样本 reward 分布</h3>
        </div>
        <div className="card-body">
          {dist.length === 0 ? (
            <div className="muted">暂无数据</div>
          ) : (
            <div style={{ display: "flex", gap: 4, alignItems: "flex-end", height: 120 }}>
              {dist.map((d) => (
                <div
                  key={d.bucket}
                  title={`${d.bucket}: ${d.count}`}
                  style={{
                    flex: 1,
                    height: `${(d.count / distMax) * 100}%`,
                    background: "var(--signal)",
                    borderRadius: "4px 4px 0 0",
                    minWidth: 8,
                  }}
                />
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
            {dist.map((d) => (
              <div key={d.bucket} style={{ flex: 1, fontSize: 9, textAlign: "center", color: "var(--text-tertiary)" }}>
                {d.bucket}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
