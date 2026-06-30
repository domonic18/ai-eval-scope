import type { ReactNode } from "react"
import { Card, CardContent } from "@/components/shadcn/card"
import { ExplainTooltip } from "@/components/ExplainTooltip"
import { cn } from "@/lib/utils"
import type { ExplainContent } from "@/lib/eval"

interface MetricCardProps {
  /** 指标标签，通常大写。 */
  label: ReactNode
  /** 指标值字符串。 */
  value: ReactNode
  /** 说明内容，存在时 label 右侧显示 ? 图标。 */
  explain?: ExplainContent
  /** 较上次变化文本，如 "+1.2%" / "持平" / "首次评估"。 */
  delta?: string | null
  /** 最近一次运行时间文案，如 "3 天前"。 */
  recentRunTime?: string | null
  /** 数值自定义颜色类。 */
  valueClassName?: string
  /** 数值行内样式（用于阈值着色等）。 */
  valueStyle?: React.CSSProperties
  /** 卡片自定义类名。 */
  className?: string
}

/** 项目概览/运行详情用指标卡。
 *  风格对齐最新设计稿：仪器读数、等宽数字、阈值着色、hover 顶边信号高光、
 *  底部「最近一次运行 X · ▲较上次 +0.035」格式。 */
export function MetricCard({
  label,
  value,
  explain,
  delta,
  recentRunTime,
  valueClassName,
  valueStyle,
  className,
}: MetricCardProps) {
  const deltaValue = delta === "首次评估" ? null : delta
  const deltaCls = deltaValue
    ? deltaValue.startsWith("+")
      ? "text-emerald-400"
      : deltaValue.startsWith("-")
        ? "text-red-400"
        : "text-muted-foreground"
    : undefined

  return (
    <Card
      className={cn(
        "group relative overflow-hidden transition-all hover:border-primary/30",
        className,
      )}
    >
      {/* hover 顶边信号高光 */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-primary/70 via-chart-2/70 to-primary/70 opacity-0 transition-opacity duration-200 group-hover:opacity-100"
        aria-hidden="true"
      />

      <CardContent className="pt-5">
        <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          <span>{label}</span>
          {explain && <ExplainTooltip content={explain} />}
        </div>

        <div
          className={cn(
            "mt-2 text-3xl font-bold leading-none tracking-tight tabular-nums",
            "font-mono",
            valueClassName,
          )}
          style={valueStyle}
        >
          {value}
        </div>

        <div className="mt-2 flex min-h-[16px] flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          {recentRunTime && <span>最近一次运行 {recentRunTime}</span>}
          {recentRunTime && deltaValue && <span>·</span>}
          {deltaValue && (
            <span className="inline-flex items-center gap-1">
              <span className={deltaCls}>{deltaIcon(deltaValue)} 较上次</span>
              <span className={cn("font-mono font-medium", deltaCls)}>{deltaValue}</span>
            </span>
          )}
          {delta === "首次评估" && <span>首次评估</span>}
        </div>
      </CardContent>
    </Card>
  )
}

function deltaIcon(delta: string): string {
  if (delta.startsWith("+")) return "▲"
  if (delta.startsWith("-")) return "▼"
  return "▬"
}
