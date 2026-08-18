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

/** 按指标 id（精确或尾缀匹配）取展示名；找不到回退 fallback。替代旧 METRIC_LABEL 硬编码。 */
export function metricLabelOf(defs: MetricDef[], id: string, fallback: string): string {
  const def = defs.find((d) => d.id === id || d.id.endsWith(`:${id}`))
  return def?.name ?? fallback
}

/** 按指标 id 取达标阈值；无则返回 undefined。替代旧 THRESHOLDS 硬编码。 */
export function metricThresholdOf(defs: MetricDef[], id: string): number | undefined {
  const def = defs.find((d) => d.id === id || d.id.endsWith(`:${id}`))
  return def?.threshold ?? undefined
}
