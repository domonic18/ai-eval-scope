import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useCrumbs } from "../../context/navigation"
import { Page, PageHead } from "../../components/shared"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/shadcn/card"
import { Badge } from "../../components/shadcn/badge"
import { Button } from "../../components/shadcn/button"
import { api, type Scenario } from "../../api/client"
import { Boxes, ChevronRight } from "lucide-react"

/** 配置中心入口（只读目录，docs/plan/08 纯可视化）：默认列出官方场景包（official），点选进入场景详情。 */
const errMsg = (e: unknown, fb: string) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb

/** 卡片资产计数（非零项拼接，如「规则集 2 · 提示词 3」），全零返回空。 */
function assetCounts(s: Scenario): string {
  const c = s._count
  if (!c) return ""
  const parts: string[] = []
  if (c.ruleSets) parts.push(`规则集 ${c.ruleSets}`)
  if (c.prompts) parts.push(`提示词 ${c.prompts}`)
  if (c.datasets) parts.push(`数据集 ${c.datasets}`)
  if (c.taskSets) parts.push(`任务集 ${c.taskSets}`)
  if (c.sutConfigs) parts.push(`SUT ${c.sutConfigs}`)
  return parts.join(" · ")
}

export default function ConfigHub() {
  const { setCrumbs } = useCrumbs()
  const [items, setItems] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAuto, setShowAuto] = useState(false)

  useEffect(() => {
    setCrumbs([{ label: "配置中心" }])
    api
      .scenarios()
      .then(setItems)
      .catch((e) => setError(errMsg(e, "加载场景失败")))
      .finally(() => setLoading(false))
  }, [setCrumbs])

  // 视角分流：配置中心默认只呈现官方场景包；auto_ingest（run 补缺注册）经管理员开关显式展开
  const official = useMemo(() => items.filter((s) => s.source !== "auto_ingest"), [items])
  const auto = useMemo(() => items.filter((s) => s.source === "auto_ingest"), [items])
  const shown = showAuto ? items : official

  return (
    <Page>
      <PageHead
        title="配置中心"
        sub="场景包配置资产：规则集、提示词、数据集（动态 catalog，对齐 13 配置管理设计）"
        right={
          <div className="flex gap-2">
            {auto.length > 0 && (
              <Button variant="ghost" onClick={() => setShowAuto((v) => !v)}>
                {showAuto ? "隐藏自动注册" : `显示自动注册 (${auto.length})`}
              </Button>
            )}
          </div>
        }
      />
      {error && <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">{error}</div>}
      {loading ? (
        <div className="text-sm text-muted-foreground">加载中…</div>
      ) : shown.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
            <Boxes className="size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">暂无场景。可运行 importAssetsToDb 导入内置 courseware 包。</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((s) => {
            const counts = assetCounts(s)
            return (
              <Link key={s.id} to={`/config/scenarios/${s.id}`}>
                <Card className="transition-colors hover:bg-accent/40">
                  <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
                    <div className="min-w-0">
                      <CardTitle className="flex items-center gap-2 truncate">
                        <span className="truncate">{s.name}</span>
                        {s.source === "auto_ingest" && (
                          <Badge variant="outline" className="shrink-0 text-xs text-muted-foreground">
                            自动注册
                          </Badge>
                        )}
                      </CardTitle>
                      <Badge variant="secondary" className="mt-1.5 font-mono text-xs">
                        {s.id}
                      </Badge>
                    </div>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                  </CardHeader>
                  <CardContent>
                    <p className="line-clamp-2 text-sm text-muted-foreground">
                      {s.description ?? "（无描述）"}
                    </p>
                    <p className="mt-2 text-xs text-muted-foreground/80">{counts || "（暂无配置资产）"}</p>
                  </CardContent>
                </Card>
              </Link>
            )
          })}
        </div>
      )}
    </Page>
  )
}
