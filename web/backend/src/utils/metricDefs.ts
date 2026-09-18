/**
 * run 维度指标定义解析（docs/plan/08 Web 纯可视化与指标展示锚定设计）。
 *
 * 不变量 3：run 是不可变审计事实，展示锚定该 run 自带快照（时间一致 = 审计一致，
 * 阈值/口径/名称均为执行时刻语义）；场景 defaults 仅在快照缺失/无定义时兜底（极老 run）。
 * 「当前定义解释历史数据」跨包代际必错（edu:* 旧 defaults × kb:* 新快照改名事故根因）。
 *
 * 批次 C 将提升为 DefinitionsResolver 并扩展 meta（matched/defaults 血缘）。
 */

export type MetricDefinition = Record<string, unknown>

export interface ResolvedMetricDefs {
  defs: MetricDefinition[]
  source: "run-snapshot" | "scenario-defaults" | "none"
}

/** 从 content（快照/defaults）提取 metric_definitions（兼容 camelCase 旧字段名）。 */
function extractDefs(content: unknown): MetricDefinition[] {
  if (content == null || typeof content !== "object") return []
  const c = content as Record<string, unknown>
  const defs = c.metric_definitions ?? c.metricDefinitions
  return Array.isArray(defs) ? (defs as MetricDefinition[]) : []
}

/**
 * 解析顺序：run 快照 defs → 场景 defaults defs → 空（source=none，调用方显式降级）。
 * 纯函数：两代指标 id 共存（如 edu:* 旧 defaults + kb:* run 快照）时确定性取快照。
 */
export function resolveRunMetricDefs(
  snapshotContent: unknown,
  defaultsContent: unknown,
): ResolvedMetricDefs {
  const fromSnapshot = extractDefs(snapshotContent)
  if (fromSnapshot.length > 0) return { defs: fromSnapshot, source: "run-snapshot" }
  const fromDefaults = extractDefs(defaultsContent)
  if (fromDefaults.length > 0) return { defs: fromDefaults, source: "scenario-defaults" }
  return { defs: [], source: "none" }
}
