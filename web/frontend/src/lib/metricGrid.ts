import type { MetricDef } from "@/types"

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
