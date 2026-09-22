/**
 * run 维度指标定义解析（docs/plan/08 Web 纯可视化与指标展示锚定设计）。
 *
 * 不变量 3：run 是不可变审计事实，展示锚定该 run 自带快照（时间一致 = 审计一致，
 * 阈值/口径/名称均为执行时刻语义）；场景 defaults 仅在快照缺失/无定义时兜底（极老 run）。
 * 「当前定义解释历史数据」跨包代际必错（edu:* 旧 defaults × kb:* 新快照改名事故根因）。
 *
 * 批次 C：resolveRunDefinitions 增加血缘 meta（source/snapshotHash/defaultsHash），
 * pairRunDefs 供列表端点行级配对（按 contentHash memo，重 content 不下发）。
 */

export type MetricDefinition = Record<string, unknown>

export interface ResolvedMetricDefs {
  defs: MetricDefinition[]
  source: "run-snapshot" | "scenario-defaults" | "none"
}

/** 带血缘 meta 的解析结果（批次 C）：hash 锚定 run↔登记/defaults 版本。 */
export interface ResolvedDefinitions extends ResolvedMetricDefs {
  snapshotHash: string | null
  defaultsHash: string | null
}

/** 快照/defaults 行的公共形状（Prisma 查询直接给）。 */
export interface DefsSource {
  content: unknown
  contentHash?: string | null
}

/** 从 content（快照/defaults）提取 metric_definitions（兼容 camelCase 旧字段名）。 */
function extractDefs(content: unknown): MetricDefinition[] {
  if (content == null || typeof content !== "object") return []
  const c = content as Record<string, unknown>
  const defs = c.metric_definitions ?? c.metricDefinitions
  return Array.isArray(defs) ? (defs as MetricDefinition[]) : []
}

/** 解析顺序：run 快照 defs → 场景 defaults defs → 空（source=none，调用方显式降级）。 */
function pickDefs(
  snapshotContent: unknown,
  defaultsContent: unknown,
): Pick<ResolvedDefinitions, "defs" | "source"> {
  const fromSnapshot = extractDefs(snapshotContent)
  if (fromSnapshot.length > 0) return { defs: fromSnapshot, source: "run-snapshot" }
  const fromDefaults = extractDefs(defaultsContent)
  if (fromDefaults.length > 0) return { defs: fromDefaults, source: "scenario-defaults" }
  return { defs: [], source: "none" }
}

/**
 * 批次 A 入口（RunDetail/latest-run 在用）：仅解析 defs，无血缘 meta。
 * 纯函数：两代指标 id 共存（如 edu:* 旧 defaults + kb:* run 快照）时确定性取快照。
 */
export function resolveRunMetricDefs(
  snapshotContent: unknown,
  defaultsContent: unknown,
): ResolvedMetricDefs {
  return pickDefs(snapshotContent, defaultsContent)
}

/** 批次 C 入口：解析 defs + 血缘 meta（hash 缺省为 null，不臆造）。 */
export function resolveRunDefinitions(
  snapshot: DefsSource | null | undefined,
  defaults: DefsSource | null | undefined,
): ResolvedDefinitions {
  return {
    ...pickDefs(snapshot?.content, defaults?.content),
    snapshotHash: snapshot?.contentHash ?? null,
    defaultsHash: defaults?.contentHash ?? null,
  }
}

/** pairRunDefs 的行约束：带可选快照行 + scenarioId，解析结果原地写入 metricDefinitions。 */
export interface PairableRunRow {
  scenarioId?: string | null
  runConfigSnapshot?: DefsSource | null
  metricDefinitions?: MetricDefinition[]
}

/**
 * 列表行级配对（docs/plan/08 批次 C）：每行 defs 锚定各自 run 快照；
 * 无快照/无定义的行按 scenarioId 走场景 defaults 兜底（不变量 3）。
 *
 * - 按 contentHash memo：同 hash 只解析一次；defaults 按 scenarioId memo，只取一次
 * - 原地填充 row.metricDefinitions 并删除 row.runConfigSnapshot（重 content 不下发）
 */
export async function pairRunDefs<Row extends PairableRunRow>(
  rows: Row[],
  getDefaults: (scenarioId: string) => Promise<DefsSource | null>,
): Promise<void> {
  const resolvedByHash = new Map<string, ResolvedDefinitions>()
  const defaultsByScn = new Map<string, DefsSource | null>()

  const defaultsOf = async (scenarioId: string): Promise<DefsSource | null> => {
    if (!defaultsByScn.has(scenarioId)) {
      // Promise.resolve 兼容同步/异步 getter；取失败按无 defaults 处理（不让单场景故障拖垮列表）
      defaultsByScn.set(scenarioId, await Promise.resolve(getDefaults(scenarioId)).catch(() => null))
    }
    return defaultsByScn.get(scenarioId) ?? null
  }

  for (const row of rows) {
    const snap = row.runConfigSnapshot ?? null
    const snapHash = snap?.contentHash ?? null
    let resolved: ResolvedDefinitions | undefined
    if (snapHash) {
      const cached = resolvedByHash.get(snapHash)
      if (cached) {
        resolved = cached
      } else {
        resolved = resolveRunDefinitions(snap, await defaultsOf(row.scenarioId ?? ""))
        resolvedByHash.set(snapHash, resolved)
      }
    } else {
      resolved = resolveRunDefinitions(snap, await defaultsOf(row.scenarioId ?? ""))
    }
    row.metricDefinitions = resolved.defs
    delete (row as Partial<Row>).runConfigSnapshot
  }
}
