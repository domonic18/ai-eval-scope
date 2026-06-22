import type { ReactNode } from "react"

/** 迷你火花线（dashboard 卡片用）。data 为 0~1 或任意数值，自动归一化。 */
export function Sparkline({
  data,
  color = "var(--signal)",
  width = 200,
  height = 28,
  min,
  max,
}: {
  data: number[]
  color?: string
  width?: number
  height?: number
  min?: number
  max?: number
}) {
  if (!data || data.length === 0) return null
  const lo = min ?? Math.min(...data)
  const hi = max ?? Math.max(...data)
  const range = hi - lo || 1
  const n = data.length
  const pts = data
    .map((v, i) => {
      const x = n === 1 ? 0 : (i / (n - 1)) * width
      const y = height - ((v - lo) / range) * height
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  )
}

export interface Series {
  name: string
  color: string
  data: number[] // 0~1
}

/** 多线趋势图（项目概览用），暗色网格。替代 echarts。 */
export function LineChart({ series, height = 240 }: { series: Series[]; height?: number }) {
  const W = 720
  const H = height
  const y = (v: number) => H - Math.max(0, Math.min(1, v)) * H
  const toPts = (data: number[]) =>
    data
      .map((v, i) => {
        const x = data.length === 1 ? 0 : (i / (data.length - 1)) * W
        return `${x.toFixed(1)},${y(v).toFixed(1)}`
      })
      .join(" ")
  return (
    <svg className="trend-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      {[0.25, 0.5, 0.75].map((g) => (
        <line
          key={g}
          x1="0"
          y1={y(g)}
          x2={W}
          y2={y(g)}
          stroke="var(--border)"
          strokeDasharray="3 4"
        />
      ))}
      {series.map((s) => (
        <polyline
          key={s.name}
          points={toPts(s.data)}
          fill="none"
          stroke={s.color}
          strokeWidth={2.5}
        />
      ))}
    </svg>
  )
}

/** 趋势图例。 */
export function ChartLegend({ series }: { series: Series[] }) {
  return (
    <div className="legend">
      {series.map((s) => (
        <div className="legend-item" key={s.name}>
          <span className="legend-line" style={{ background: s.color }} />
          {s.name}
        </div>
      ))}
    </div>
  )
}

/** 失败分布条形榜的一行（run-detail）。 */
export function FailBar({
  name,
  count,
  max,
  color,
  onClick,
}: {
  name: ReactNode
  count: number
  max: number
  color: string
  onClick?: () => void
}) {
  const w = max > 0 ? (count / max) * 100 : 0
  return (
    <div className="fail-row" onClick={onClick} style={onClick ? {} : { cursor: "default" }}>
      <span className="fail-name" style={{ width: "max-content" }}>
        {name}
      </span>
      <div className="fail-track">
        <div className="fail-fill" style={{ width: `${w}%`, background: color }} />
      </div>
      <span className="fail-n">{count}</span>
    </div>
  )
}
