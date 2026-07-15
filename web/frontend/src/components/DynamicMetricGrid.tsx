/**
 * Phase 5 场景化指标动态网格（对齐 09 §9.5.5、13）。
 *
 * 按 MetricDefinition[] + metrics 键值渲染指标卡。阈值/名称/单位/说明均来自
 * metricDefinitions（运行快照 或 useScenarioDefaults fetch），无任何前端 hardcode。
 *
 * 指标说明（? hover 提示）为可选：MetricDef.explain 定义时显示，否则不显示。
 */
import { MetricCard } from "./MetricCard"
import type { ExplainContent } from "../lib/eval"
import type { MetricDef, MetricExplain } from "../types"

/** dd 行 tone → 颜色（强调重点）。 */
const TONE_COLOR: Record<NonNullable<MetricExplain["rows"][number]["tone"]>, string> = {
  default: "var(--muted-foreground)",
  primary: "var(--text-primary)",
  danger: "var(--destructive)",
  success: "var(--chart-2)",
  warning: "var(--chart-4)",
}

/** 可序列化 MetricExplain → MetricCard 用的 ExplainContent（ReactNode）。 */
function toExplainContent(e: MetricExplain): ExplainContent {
  return {
    title: e.title,
    rows: e.rows.map((r) => ({
      dt: r.dt,
      dd: <span style={{ color: TONE_COLOR[r.tone ?? "default"] }}>{r.dd}</span>,
    })),
  }
}

function fmt(v: number | undefined): string {
  if (v == null || Number.isNaN(v)) return "—"
  return v.toFixed(3)
}

export function DynamicMetricGrid({
  defs,
  metrics,
}: {
  defs: MetricDef[]
  metrics: Record<string, number> | null | undefined
}) {
  if (!defs || defs.length === 0) return null
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {defs.map((d) => {
        const val = metrics?.[d.id]
        const hasThr = d.threshold != null
        const pass = hasThr && typeof val === "number" && val >= (d.threshold as number)
        const explain = d.explain ? toExplainContent(d.explain) : undefined
        return (
          <MetricCard
            key={d.id}
            label={d.name ?? d.id}
            value={fmt(val)}
            explain={explain}
            valueClassName={
              hasThr ? (pass ? "text-emerald-400" : "text-red-400") : undefined
            }
          />
        )
      })}
    </div>
  )
}

/** 从运行详情的 runConfigSnapshot.content 取 metricDefinitions（兼容字段名）。 */
export function extractMetricDefs(
  snapshot: { content: Record<string, unknown> } | null | undefined,
): MetricDef[] {
  if (!snapshot?.content) return []
  const defs = (snapshot.content.metric_definitions ?? snapshot.content.metricDefinitions) as
    | MetricDef[]
    | undefined
  return Array.isArray(defs) ? defs : []
}
