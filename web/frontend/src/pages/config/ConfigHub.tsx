import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useCrumbs } from "../../components/AppShell"
import { Page, PageHead } from "../../components/shared"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/shadcn/card"
import { Badge } from "../../components/shadcn/badge"
import { api, type Scenario } from "../../api/client"
import { Boxes, ChevronRight } from "lucide-react"

/** 配置中心入口：列出全部场景，点选进入场景详情（规则集/提示词/数据集 catalog）。 */
const errMsg = (e: unknown, fb: string) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb

export default function ConfigHub() {
  const { setCrumbs } = useCrumbs()
  const [items, setItems] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setCrumbs([{ label: "配置中心" }])
    api
      .scenarios()
      .then(setItems)
      .catch((e) => setError(errMsg(e, "加载场景失败")))
      .finally(() => setLoading(false))
  }, [setCrumbs])

  return (
    <Page>
      <PageHead
        title="配置中心"
        sub="场景包配置资产：规则集、提示词、数据集（动态 catalog，对齐 13 配置管理设计）"
      />
      {error && <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">{error}</div>}
      {loading ? (
        <div className="text-sm text-muted-foreground">加载中…</div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
            <Boxes className="size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">暂无场景。可运行 importAssetsToDb 导入内置 courseware 包。</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((s) => (
            <Link key={s.id} to={`/config/scenarios/${s.id}`}>
              <Card className="transition-colors hover:bg-accent/40">
                <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
                  <div className="min-w-0">
                    <CardTitle className="flex items-center gap-2 truncate">
                      <span className="truncate">{s.name}</span>
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
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </Page>
  )
}
