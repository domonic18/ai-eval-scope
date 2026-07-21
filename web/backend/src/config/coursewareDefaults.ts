/**
 * courseware 场景默认指标定义（backend 单一 TS 源）。
 *
 * 镜像 evaluator agent_eval/evaluation/scenario/defaults.py 的 COURSEWARE_DEFAULT_METRICS。
 * 用于：
 *  - 历史迁移脚本回填 RunConfigSnapshot（migrateHistoricalMetrics）
 *  - importAssetsToDb 写入 Scenario.defaultMetricDefinitions（供前端列表页 fetch）
 *
 * 前端不再 hardcode 任何场景指标定义，统一从 GET /scenarios/:id/defaults 取。
 * 跨语言同步（TS↔Python）后续可收敛到 courseware 包内 metrics/policy.yaml。
 */

export interface MetricExplainRow {
  dt: string
  dd: string
  tone?: "default" | "primary" | "danger" | "success" | "warning"
}
export interface MetricExplain {
  title: string
  rows: MetricExplainRow[]
}
export interface MetricDefDTO {
  id: string
  name: string
  expression: string
  threshold: number | null
  unit: string
  summary?: string
  explain?: MetricExplain
}

/** courseware 默认指标定义（含 explain + summary，对齐 evaluator Phase 1）。 */
export const COURSEWARE_DEFAULT_METRIC_DEFS: MetricDefDTO[] = [
  {
    id: "courseware:document_rate",
    name: "交付率 DR",
    expression: "count(format_gate) / total",
    threshold: 0.95,
    unit: "ratio",
    summary: "所有样本的格式是否合规（能不能正常打开和使用）",
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
    expression: "count(both(format_gate, commonsense_gate)) / total",
    threshold: 0.9,
    unit: "ratio",
    summary: "内容是否存在事实错误或常识问题",
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
    expression: "mean(reward)",
    threshold: 0.7,
    unit: "score",
    summary: "综合质量评分（格式 + 内容 + 质量 + 偏好加权平均）",
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
    expression: "mean(s_soft)",
    threshold: null,
    unit: "score",
    summary: "内容本身的质量（教学逻辑、多样性、可读性等）",
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
    expression: "mean(s_pref)",
    threshold: null,
    unit: "score",
    summary: "是否符合用户主观喜好（风格、深度、需求契合度等）",
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
    expression: "gated_mean(reward, format_gate, commonsense_gate)",
    threshold: null,
    unit: "score",
    summary: "合格样本的平均质量（排除格式不合格的）",
    explain: {
      title: "CondR · Conditional Reward",
      rows: [
        { dt: "定义", dd: "仅统计通过双门控样本的 Reward 均值——排除格式/常识失败后的真实质量。", tone: "primary" },
        { dt: "范围", dd: "[0, 1]" },
      ],
    },
  },
]

/** courseware 默认聚合策略（镜像 evaluator）。 */
export const COURSEWARE_DEFAULT_AGGREGATION_POLICY = {
  id: "courseware-default",
  scenario_id: "courseware",
  stage_weights: [
    { stage_id: "format", weight: 1.0, is_gate: true },
    { stage_id: "commonsense", weight: 1.0, is_gate: true },
    {
      stage_id: "quality",
      weight: 1.0,
      is_gate: false,
      skip_tiers_in_reward: ["hard_gate", "hard_score"],
    },
  ],
  normalize_to: [0.0, 1.0],
}
