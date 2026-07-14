/**
 * Phase 5 场景化指标动态网格（对齐 09 §9.5.5、13）。
 *
 * 按 MetricDefinition[] + metrics 键值渲染指标卡，取代 lib/eval.tsx 中写死的
 * DR/CPR/Reward/Soft/Pref/CondR。阈值/名称/单位均来自 metricDefinitions，
 * 课件与新场景统一渲染，无任何场景专用 fallback。
 */
import { MetricCard } from "./MetricCard"
import type { MetricDef } from "../types"

/**
 * courseware 默认指标定义（镜像 evaluator Phase 1 COURSEWARE_DEFAULT_METRICS）。
 * 项目级列表页（Dashboard/ProjectDetail/Admin）无单一运行快照时，用此默认集渲染
 * run.metrics；运行自身有快照时优先用快照的 metric_definitions。
 */
export const COURSEWARE_DEFAULT_METRIC_DEFS: MetricDef[] = [
  { id: "courseware:document_rate", name: "交付率 DR", threshold: 0.95, unit: "ratio" },
  { id: "courseware:constraint_pass_rate", name: "约束通过率 CPR", threshold: 0.9, unit: "ratio" },
  { id: "courseware:reward", name: "平均 Reward", threshold: 0.7, unit: "score" },
  { id: "courseware:soft", name: "内容质量", unit: "score" },
  { id: "courseware:pref", name: "用户偏好", unit: "score" },
  { id: "courseware:conditional_reward", name: "条件 Reward", unit: "score" },
]

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
        return (
          <MetricCard
            key={d.id}
            label={d.name ?? d.id}
            value={fmt(val)}
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
