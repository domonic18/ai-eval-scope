import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { api } from "../api/client"
import type { DashboardProject, TrendPoint } from "../types"
import { fmt3, num, timeAgo } from "../lib/format"
import { METRIC_LABEL } from "../lib/eval"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Label } from "@/components/shadcn/label"
import { Card, CardContent } from "@/components/shadcn/card"
import { Skeleton } from "@/components/shadcn/skeleton"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import { Sparkline } from "@/components/Sparkline"
import { useCrumbs, useOrg } from "../components/AppShell"
import { useToast } from "../components/toast"
import { Page, PageHead, SemPill, type PillTone } from "../components/shared"
import { Plus, RefreshCw } from "lucide-react"

/** Phase 5：优先从 metrics 取场景化指标，回落遗留列（P5-8 删列后为唯一来源）。 */
const drOf = (p: DashboardProject) =>
  p.latestRun?.metrics?.["courseware:document_rate"] ?? p.latestRun?.dr
const rewardOf = (p: DashboardProject) =>
  p.latestRun?.metrics?.["courseware:reward"] ?? p.latestRun?.avgReward

function healthColor(p: DashboardProject): { tone: PillTone; spark: string; label: string } {
  const dr = drOf(p)
  if (dr == null) return { tone: "neutral", spark: "var(--muted-foreground)", label: "未运行" }
  if (dr >= 0.95) return { tone: "success", spark: "var(--chart-2)", label: "健康" }
  return { tone: "warning", spark: "var(--chart-3)", label: "关注" }
}

export default function Dashboard() {
  const { activeOrg } = useOrg()
  const { setCrumbs } = useCrumbs()
  const toast = useToast()
  const nav = useNavigate()
  const [projects, setProjects] = useState<DashboardProject[] | null>(null)
  const [sparks, setSparks] = useState<Record<string, number[]>>({})
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState("")
  const [slug, setSlug] = useState("")
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    setCrumbs([{ label: "项目看板" }])
  }, [setCrumbs])

  async function load() {
    if (!activeOrg) {
      setProjects([])
      return
    }
    setProjects(null)
    setSparks({})
    try {
      const ps: DashboardProject[] = await api.dashboard(activeOrg)
      setProjects(ps)
      const entries = await Promise.all(
        ps.map(async (p): Promise<[string, number[]]> => {
          try {
            const t: TrendPoint[] = await api.projectTrends(p.id, 8)
            return [p.id, t.map((x) => x.DR).filter((v): v is number => v != null)]
          } catch {
            return [p.id, []]
          }
        }),
      )
      setSparks(Object.fromEntries(entries))
    } catch {
      setProjects([])
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOrg])

  async function doCreate() {
    if (!activeOrg || !name.trim() || !slug.trim()) {
      toast.error("请填写项目名称与 Slug")
      return
    }
    if (!/^[a-z0-9][a-z0-9-]*$/.test(slug.trim())) {
      toast.error("Slug 仅允许小写字母、数字与连字符")
      return
    }
    setCreating(true)
    try {
      const p = await api.createProject(activeOrg, name.trim(), slug.trim())
      toast.success("项目已创建")
      setCreateOpen(false)
      setName("")
      setSlug("")
      nav(`/project/${p.id}`)
    } catch (e) {
      toast.error("创建失败：" + ((e as Error).message ?? ""))
    } finally {
      setCreating(false)
    }
  }

  return (
    <Page>
      <PageHead
        title="项目看板"
        sub="我的全部评估项目"
        right={
          <div className="flex gap-2">
            <Button variant="outline" onClick={load}>
              <RefreshCw className="size-4" /> 刷新
            </Button>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" /> 新建项目
            </Button>
          </div>
        }
      />

      {projects === null ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Card key={i}>
              <CardContent className="space-y-3 pt-6">
                <Skeleton className="h-4 w-3/5" />
                <Skeleton className="h-7 w-full" />
                <Skeleton className="h-4 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : projects.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center text-sm text-muted-foreground">
            暂无评估项目。点击右上角「新建项目」创建第一个评估项目。
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => {
            const h = healthColor(p)
            const drVal = drOf(p)
            const drCls = drVal == null ? "text-muted-foreground" : drVal >= 0.95 ? "text-emerald-400" : "text-yellow-400"
            return (
              <Link key={p.id} to={`/project/${p.id}`} className="block">
                <Card className="transition-all hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-md">
                  <CardContent className="space-y-3 p-[18px]">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-[15px] font-semibold">{p.name}</div>
                        <div className="truncate text-xs text-muted-foreground">
                          {p.slug} · 创建者 {p.ownerName}
                        </div>
                      </div>
                      <SemPill tone={h.tone} dot={drVal != null} className="shrink-0">
                        {h.label}
                      </SemPill>
                    </div>

                    <div className="flex h-7 items-center">
                      {(sparks[p.id]?.length ?? 0) > 1 ? (
                        <Sparkline data={sparks[p.id]} color={h.spark} width={260} height={28} />
                      ) : (
                        <span className="text-xs text-muted-foreground/60">
                          {p.latestRun ? "暂无趋势数据" : ""}
                        </span>
                      )}
                    </div>

                    <div className="grid grid-cols-3 gap-2 border-y py-3.5">
                      <div>
                        <div className={`font-mono text-lg font-semibold tabular-nums ${drCls}`}>
                          {fmt3(drOf(p))}
                        </div>
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                          {METRIC_LABEL.DR}
                        </div>
                      </div>
                      <div>
                        <div className="font-mono text-lg font-semibold tabular-nums">
                          {fmt3(rewardOf(p))}
                        </div>
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                          {METRIC_LABEL.Reward}
                        </div>
                      </div>
                      <div>
                        <div className="font-mono text-lg font-semibold tabular-nums">{num(p.runCount)}</div>
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">运行数</div>
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>
                        {p.latestRun ? `最近运行 ${timeAgo(p.latestRun.createdAt)}` : "等待首个运行接入"}
                      </span>
                      {p.latestRun && <span className="font-mono">#{p.latestRun.runId.slice(-8)}</span>}
                    </div>
                  </CardContent>
                </Card>
              </Link>
            )
          })}

          <button
            onClick={() => setCreateOpen(true)}
            className="flex min-h-[180px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary"
          >
            <Plus className="size-7" />
            <span className="text-sm font-medium">新建项目</span>
          </button>
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
            <DialogDescription>项目是评估数据的容器，对应一类被测 Agent</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="p-name">项目名称</Label>
              <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：课件生成评估" autoFocus />
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-slug">Slug（项目唯一标识）</Label>
              <Input id="p-slug" className="font-mono" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="courseware" />
              <p className="text-xs text-muted-foreground">用于接入标识与 URL，仅小写字母、数字、连字符</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button onClick={doCreate} disabled={creating}>
              {creating ? "创建中…" : "创建并配置接入"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  )
}
