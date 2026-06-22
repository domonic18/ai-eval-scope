import { useEffect } from "react"
import { useCrumbs, Empty } from "../components/ui"
import { IconBook } from "../components/icons"

/** 占位页：原型中尚未落地的页面（全部运行 / 成员 / 组织设置）。 */
export default function ComingSoon({ title }: { title: string }) {
  const { setCrumbs } = useCrumbs()
  useEffect(() => {
    setCrumbs([{ label: title }])
  }, [title, setCrumbs])

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>{title}</h1>
          <div className="sub">该页面将在后续迭代上线</div>
        </div>
      </div>
      <div className="card r-2">
        <div className="card-body">
          <Empty
            icon={<IconBook size={40} />}
            title={`${title} 页面规划中`}
            children={<>对应高保真原型已就绪，将随后续迭代落地。</>}
          />
        </div>
      </div>
    </div>
  )
}
