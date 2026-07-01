/** 超管后台 · 总览（shadcn/ui + Recharts 重写）：规模卡 + 指标趋势 + score 分布。 */
import { useEffect, useState } from "react"
import { Area, AreaChart, Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"
import { api } from "../../api/client"
import { Badge } from "@/components/shadcn/badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/shadcn/alert"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/shadcn/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/shadcn/chart"
import { num, fmtBytes } from "../../lib/format"
import { Page } from "../../components/shared"

interface Overview {
  users: { total: number; active: number; disabled: number; admins: number }
  orgs: number
  projects: { total: number; archived: number }
  runs: { total: number; completed: number; failed: number; pending: number }
  samples: number
  artifacts: { total: number; storageBytes: number }
}

const trendConfig = {
  DR: { label: "DR", color: "var(--chart-1)" },
  Reward: { label: "Reward", color: "var(--chart-2)" },
} satisfies ChartConfig
const distConfig = { count: { label: "样本数", color: "var(--chart-2)" } } satisfies ChartConfig

function StatCard({ label, value, foot }: { label: string; value: string; foot?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tracking-tight tabular-nums">{value}</div>
        {foot && <p className="mt-1 text-xs text-muted-foreground">{foot}</p>}
      </CardContent>
    </Card>
  )
}

export default function AdminOverview() {
  const [ov, setOv] = useState<Overview | null>(null)
  const [trends, setTrends] = useState<{ created_at: string; DR: number; Reward: number }[]>([])
  const [dist, setDist] = useState<{ bucket: string; count: number }[]>([])
  const [err, setErr] = useState("")

  useEffect(() => {
    Promise.all([api.adminOverview(), api.adminTrends(100), api.adminScoreDistribution()])
      .then(([o, t, d]) => {
        setOv(o)
        setTrends(t.map((p) => ({ created_at: p.created_at, DR: p.DR, Reward: p.Reward })))
        setDist(d)
      })
      .catch((e) => setErr((e as Error).message))
  }, [])

  if (err)
    return (
      <div className="p-8">
        <Alert variant="destructive">
          <AlertTitle>加载失败</AlertTitle>
          <AlertDescription>{err}</AlertDescription>
        </Alert>
      </div>
    )
  if (!ov)
    return <div className="p-8 text-muted-foreground">加载中…</div>

  const trendData = trends.map((t, i) => ({ i: i + 1, DR: t.DR, Reward: t.Reward }))

  return (
    <Page>
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">平台总览</h1>
        <Badge variant="secondary">super admin</Badge>
      </div>

      {/* 规模卡 */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <StatCard label="用户" value={num(ov.users.total)} foot={`活跃 ${ov.users.active} · 禁用 ${ov.users.disabled} · 超管 ${ov.users.admins}`} />
        <StatCard label="工作组" value={num(ov.orgs)} />
        <StatCard label="项目" value={num(ov.projects.total)} foot={`归档 ${ov.projects.archived}`} />
        <StatCard label="评估任务" value={num(ov.runs.total)} foot={`完成 ${ov.runs.completed} · 失败 ${ov.runs.failed} · 进行 ${ov.runs.pending}`} />
        <StatCard label="样本" value={num(ov.samples)} />
        <StatCard label="产出物" value={num(ov.artifacts.total)} foot={fmtBytes(ov.artifacts.storageBytes)} />
      </div>

      {/* 趋势 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">DR / Reward 趋势（最近 {trends.length} 次运行）</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartContainer config={trendConfig} className="h-[240px] w-full">
              <AreaChart data={trendData} margin={{ left: 4, right: 8, top: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis dataKey="i" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} />
                <YAxis domain={[0, 1]} tickLine={false} axisLine={false} width={32} fontSize={11} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Area dataKey="DR" type="monotone" stroke="var(--color-DR)" fill="var(--color-DR)" fillOpacity={0.12} strokeWidth={2} />
                <Area dataKey="Reward" type="monotone" stroke="var(--color-Reward)" fill="var(--color-Reward)" fillOpacity={0.12} strokeWidth={2} />
              </AreaChart>
            </ChartContainer>
          </CardContent>
        </Card>

        {/* score 分布 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">样本 reward 分布</CardTitle>
          </CardHeader>
          <CardContent>
            {dist.length === 0 ? (
              <div className="text-sm text-muted-foreground">暂无数据</div>
            ) : (
              <ChartContainer config={distConfig} className="h-[240px] w-full">
                <BarChart data={dist} margin={{ left: 4, right: 8, top: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="bucket" tickLine={false} axisLine={false} tickMargin={8} fontSize={10} interval={0} />
                  <YAxis tickLine={false} axisLine={false} width={32} fontSize={11} allowDecimals={false} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Bar dataKey="count" fill="var(--color-count)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ChartContainer>
            )}
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
