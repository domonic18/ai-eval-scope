import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react"

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

/** 通用趋势图：自适应 y 轴 + 坐标刻度 + 数据点 hover tooltip + 阈值参考线。
 * 替代早期假设 data∈[0,1] 的 LineChart：支持任意取值范围（如 Reward 负值、0 值），0/负值均可见。
 * 行业可观测实践：y 自适应、刻度标注、参考线、hover 查看精确值。 */
export interface TrendSeries {
  key: string
  name: string
  color: string
}
export interface TrendPointData {
  label: string
  values: Record<string, number>
}
export interface TrendThreshold {
  label: string
  value: number
  color: string
}
export function TrendChart({
  points,
  series,
  height = 260,
  thresholds = [],
}: {
  points: TrendPointData[]
  series: TrendSeries[]
  height?: number
  thresholds?: TrendThreshold[]
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(760)
  const [hover, setHover] = useState<number | null>(null)
  const [hidden, setHidden] = useState<Set<string>>(new Set())

  // 响应式宽度：填满容器（与其他显示区域一致），viewBox = 容器实际像素 → 无变形
  useEffect(() => {
    const el = wrapRef.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0].contentRect.width
      if (cw > 0) setW(cw)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (!points.length) return null
  const H = height
  const padL = 46
  const padR = 16
  const padT = 14
  const padB = 26
  const plotW = Math.max(1, w - padL - padR)
  const plotH = H - padT - padB

  // 仅未隐藏的系列参与绘制与 y 轴范围
  const visibleSeries = series.filter((s) => !hidden.has(s.key))

  // y 自适应：可见点值 + 阈值，取 min/max 并留 10% padding（0/负值不被裁剪）
  const vals: number[] = []
  for (const p of points) for (const s of visibleSeries) vals.push(p.values[s.key] ?? 0)
  for (const t of thresholds) vals.push(t.value)
  let lo = Math.min(...vals)
  let hi = Math.max(...vals)
  const span = hi - lo || 1
  lo -= span * 0.1
  hi += span * 0.1
  const yOf = (v: number) => padT + plotH - ((v - lo) / (hi - lo)) * plotH
  const xOf = (i: number) =>
    padL + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW)
  const fmt = (v: number) => {
    const r = Math.abs(hi - lo)
    if (r >= 5) return v.toFixed(1)
    if (r >= 1) return v.toFixed(2)
    return v.toFixed(3)
  }
  const yTicks = [0, 1 / 3, 2 / 3, 1].map((f) => lo + (hi - lo) * f)
  const xIdx =
    points.length <= 1
      ? [0]
      : points.length === 2
        ? [0, 1]
        : [0, Math.floor((points.length - 1) / 2), points.length - 1]

  // 鼠标移动 → 吸附到最近数据点（hover 跟随 tooltip + crosshair）
  const handleMove = (e: MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const vx = ((e.clientX - rect.left) / rect.width) * w
    if (vx < padL || vx > w - padR) {
      setHover(null)
      return
    }
    let nearest = 0
    let minD = Infinity
    for (let i = 0; i < points.length; i++) {
      const d = Math.abs(xOf(i) - vx)
      if (d < minD) {
        minD = d
        nearest = i
      }
    }
    setHover(nearest)
  }
  const tipPct = hover != null ? (xOf(hover) / w) * 100 : 0
  const tipLeft = Math.min(Math.max(tipPct, 12), 88)

  return (
    <div ref={wrapRef} style={{ position: "relative", width: "100%" }}>
      <svg
        className="trend-svg"
        viewBox={`0 0 ${w} ${H}`}
        width="100%"
        height={H}
        preserveAspectRatio="none"
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
      >
        {/* y 刻度 + 水平网格 */}
        {yTicks.map((tv, i) => (
          <g key={`y${i}`}>
            <line x1={padL} y1={yOf(tv)} x2={w - padR} y2={yOf(tv)} stroke="var(--border)" strokeDasharray="3 4" />
            <text x={padL - 6} y={yOf(tv) + 3} textAnchor="end" fontSize={10} fill="var(--text-tertiary)">
              {fmt(tv)}
            </text>
          </g>
        ))}
        {/* 阈值参考线 */}
        {thresholds.map((t) => (
          <g key={t.label}>
            <line
              x1={padL}
              y1={yOf(t.value)}
              x2={w - padR}
              y2={yOf(t.value)}
              stroke={t.color}
              strokeDasharray="6 3"
              strokeWidth={1.5}
              opacity={0.75}
            />
            <text x={w - padR} y={yOf(t.value) - 3} textAnchor="end" fontSize={9} fill={t.color}>
              {t.label}
            </text>
          </g>
        ))}
        {/* hover crosshair（垂直辅助线） */}
        {hover != null && (
          <line
            x1={xOf(hover)}
            y1={padT}
            x2={xOf(hover)}
            y2={H - padB}
            stroke="var(--text-tertiary)"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        )}
        {/* 折线 */}
        {visibleSeries.map((s) => {
          const d = points
            .map((p, i) => `${xOf(i).toFixed(1)},${yOf(p.values[s.key] ?? 0).toFixed(1)}`)
            .join(" ")
          return <polyline key={s.key} points={d} fill="none" stroke={s.color} strokeWidth={2} />
        })}
        {/* 数据点（hover 时高亮放大） */}
        {points.map((p, i) => (
          <g key={`pt${i}`}>
            {visibleSeries.map((s) => (
              <circle
                key={s.key}
                cx={xOf(i)}
                cy={yOf(p.values[s.key] ?? 0)}
                r={hover === i ? 5 : 3}
                fill="var(--bg)"
                stroke={s.color}
                strokeWidth={2}
              />
            ))}
          </g>
        ))}
        {/* x 轴标签（首/中/尾） */}
        {xIdx.map((i) => (
          <text
            key={`x${i}`}
            x={xOf(i)}
            y={H - 8}
            textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
            fontSize={10}
            fill="var(--text-tertiary)"
          >
            {points[i].label}
          </text>
        ))}
      </svg>
      <div className="legend" style={{ marginTop: 4, flexWrap: "wrap" }}>
        {series.map((s) => {
          const off = hidden.has(s.key)
          return (
            <div
              key={s.key}
              className="legend-item"
              onClick={() =>
                setHidden((h) => {
                  const n = new Set(h)
                  if (n.has(s.key)) n.delete(s.key)
                  else n.add(s.key)
                  return n
                })
              }
              style={{
                opacity: off ? 0.4 : 1,
                cursor: "pointer",
                textDecoration: off ? "line-through" : "none",
                userSelect: "none",
              }}
            >
              <span className="legend-line" style={{ background: s.color }} />
              {s.name}
            </div>
          )
        })}
      </div>
      {/* hover tooltip：跟随鼠标所在数据点，显示时间 + 各指标值 */}
      {hover != null && (
        <div
          style={{
            position: "absolute",
            left: `${tipLeft}%`,
            top: 4,
            transform: "translateX(-50%)",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "6px 10px",
            fontSize: 12,
            boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
            pointerEvents: "none",
            whiteSpace: "nowrap",
            zIndex: 10,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>{points[hover].label}</div>
          {visibleSeries.map((s) => (
            <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 120 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: s.color }} />
              <span style={{ color: "var(--text-secondary)" }}>{s.name}</span>
              <span style={{ marginLeft: "auto", fontWeight: 600 }}>
                {fmt(points[hover].values[s.key] ?? 0)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
