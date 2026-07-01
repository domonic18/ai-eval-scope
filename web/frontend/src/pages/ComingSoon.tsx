import { useEffect } from "react"
import { useCrumbs } from "../components/AppShell"
import { Page, PageHead } from "../components/shared"
import { BookOpen } from "lucide-react"

/** 占位页：原型中尚未落地的页面（全部运行）。 */
export default function ComingSoon({ title }: { title: string }) {
  const { setCrumbs } = useCrumbs()
  useEffect(() => {
    setCrumbs([{ label: title }])
  }, [title, setCrumbs])

  return (
    <Page>
      <PageHead title={title} sub="该页面将在后续迭代上线" />
      <div className="rounded-lg border bg-card p-10 text-center text-card-foreground">
        <BookOpen className="mx-auto size-10 text-muted-foreground" />
        <h3 className="mt-3 font-medium">{title} 页面规划中</h3>
        <p className="mt-1 text-sm text-muted-foreground">对应高保真原型已就绪，将随后续迭代落地。</p>
      </div>
    </Page>
  )
}
