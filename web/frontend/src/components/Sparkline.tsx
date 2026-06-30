/** 迷你火花线（dashboard 卡片用）。纯 SVG，自动归一化。 */

export function Sparkline({
  data,
  color = "var(--chart-2)",
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
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-full w-full">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  )
}
