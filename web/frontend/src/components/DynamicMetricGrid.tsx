/**
 * Phase 5 场景化指标动态网格（对齐 09 §9.5.5、13）。
 *
 * 按 MetricDefinition[] + metrics 键值渲染指标卡，取代 lib/eval.tsx 中写死的
 * DR/CPR/Reward/Soft/Pref/CondR。阈值/名称/单位/说明均来自 metricDefinitions，
 * 课件与新场景统一渲染，无任何场景专用 fallback。
 *
 * 指标说明（? hover 提示）为可选：MetricDef.explain 定义时显示，否则不显示。
 */
import { MetricCard } from "./MetricCard"
import type { ExplainContent } from "../lib/eval"
import type { MetricDef, MetricExplain } from "../types"

/** dd 行 tone → 颜色（强调重点，对齐旧 METRIC_EXPLAIN 的彩色高亮）。 */
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

/**
 * courseware 默认指标定义（镜像 evaluator Phase 1 COURSEWARE_DEFAULT_METRICS）。
 * 项目级列表页（Dashboard/ProjectDetail/Admin）无单一运行快照时，用此默认集渲染
 * run.metrics；运行自身有快照时优先用快照的 metric_definitions。
 * 含各指标的 explain（hover ? 说明），与旧 METRIC_EXPLAIN 等价。
 */
export const COURSEWARE_DEFAULT_METRIC_DEFS: MetricDef[] = [
  {
    id: "courseware:document_rate",
    name: "交付率 DR",
    threshold: 0.95,
    unit: "ratio",
    explain: {
      title: "DR · Delivery Rate 交付率",
      rows: [
        { dt: "定义", dd: "能正常打开、格式符合基本要求的样本占多少——连格式都不对就没法使用。", tone: "primary" },
        { dt: "计算", dd: "格式合格的样本数 ÷ 全部样本数" },
        { dt: "标准", dd: "达标线 ≥ 0.95（即 95%）；低于则这批整体不合格。", tone: "danger" },
      ],
    },
  },
  {
    id: "courseware:constraint_pass_rate",
    name: "约束通过率 CPR",
    threshold: 0.9,
    unit: "ratio",
    explain: {
      title: "CPR · Constraint Pass Rate 约束通过率",
      rows: [
        { dt: "定义", dd: "格式 + 常识双门控都通过的样本占比——内容基本正确、无明显硬伤。", tone: "primary" },
        { dt: "计算", dd: "双门控通过样本数 ÷ 全部样本数" },
        { dt: "标准", dd: "达标线 ≥ 0.90；低于则存在较多常识性错误。", tone: "danger" },
      ],
    },
  },
  {
    id: "courseware:reward",
    name: "平均 Reward",
    threshold: 0.7,
    unit: "score",
    explain: {
      title: "Reward · 综合评分",
      rows: [
        { dt: "定义", dd: "归一化到 [0,1] 的综合质量分，融合门控与软/偏好质量。", tone: "primary" },
        { dt: "计算", dd: "(S_format + S_common + S_soft + S_pref) / 4" },
        { dt: "标准", dd: "达标线 ≥ 0.70；综合质量合格。", tone: "success" },
      ],
    },
  },
  {
    id: "courseware:soft",
    name: "内容质量",
    unit: "score",
    explain: {
      title: "Soft · 内容质量分",
      rows: [
        { dt: "定义", dd: "教学逻辑、内容多样性等软约束维度的平均得分（独立指标，不混入 Reward）。", tone: "primary" },
        { dt: "范围", dd: "[0, 1]，越高越好" },
      ],
    },
  },
  {
    id: "courseware:pref",
    name: "用户偏好",
    unit: "score",
    explain: {
      title: "Pref · 用户偏好分",
      rows: [
        { dt: "定义", dd: "风格、深度、需求满足度等偏好维度的平均得分（独立指标）。", tone: "primary" },
        { dt: "范围", dd: "[0, 1]，越高越好" },
      ],
    },
  },
  {
    id: "courseware:conditional_reward",
    name: "条件 Reward",
    unit: "score",
    explain: {
      title: "CondR · Conditional Reward",
      rows: [
        { dt: "定义", dd: "仅统计通过双门控样本的 Reward 均值——排除格式/常识失败后的真实质量。", tone: "primary" },
        { dt: "范围", dd: "[0, 1]" },
      ],
    },
  },
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
