/**
 * courseware 场景默认指标定义（backend TS 镜像）—— **仅历史迁移脚本使用**。
 *
 * 镜像 evaluator 包内 agent_eval/assets/packages/courseware/1.0.0/metrics/policy.yaml
 * （真相源 = policy.yaml，importAssetsToDb 从其写入 Scenario.defaultMetricDefinitions）。
 * 运行时（listRuns/overview/useScenarioDefaults 等）已全部走 DB defaults，不读本文件；
 * 唯一消费方是 scripts/migrateHistoricalMetrics.ts（一次性回填 courseware 历史运行的指标定义，
 * 因历史运行本就是 courseware，用 courseware 默认正确）。非 courseware 场景的 defaults 走 DB。
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

/** courseware 默认指标定义（含 explain + summary，对齐 policy.yaml）。 */
export const COURSEWARE_DEFAULT_METRIC_DEFS: MetricDefDTO[] = [
  {
    id: "courseware:document_rate",
    name: "格式合格率",
    expression: "count(format_gate) / total",
    threshold: 0.95,
    unit: "ratio",
    summary: "所有样本的格式是否合规（能不能正常打开和使用）",
    explain: {
      title: "格式合格率 · Delivery Rate",
      rows: [
        { dt: "定义", dd: "能正常打开、格式符合基本要求的样本占多少——连格式都不对就没法使用。", tone: "primary" },
        { dt: "计算", dd: "格式合格的样本数 ÷ 全部样本数" },
        { dt: "标准", dd: "达标线 ≥ 0.95（即 95%）；低于则这批整体不合格。", tone: "danger" },
      ],
    },
  },
  {
    id: "courseware:constraint_pass_rate",
    name: "内容合格率",
    expression: "count(both(format_gate, commonsense_gate)) / total",
    threshold: 0.9,
    unit: "ratio",
    summary: "内容是否存在事实错误或常识问题",
    explain: {
      title: "内容合格率 · Constraint Pass Rate",
      rows: [
        { dt: "定义", dd: "格式 + 常识双门控都通过的样本占比——内容基本正确、无明显硬伤。", tone: "primary" },
        { dt: "计算", dd: "双门控通过样本数 ÷ 全部样本数" },
        { dt: "标准", dd: "达标线 ≥ 0.90；低于则存在较多常识性错误。", tone: "danger" },
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
      title: "内容质量 · Soft 质量分",
      rows: [
        { dt: "定义", dd: "教学逻辑、内容多样性等软约束维度的平均得分（独立指标，不混入综合得分）。", tone: "primary" },
        { dt: "范围", dd: "[0, 1]，越高越好" },
      ],
    },
  },
  {
    id: "courseware:pref",
    name: "偏好匹配度",
    expression: "mean(s_pref)",
    threshold: null,
    unit: "score",
    summary: "是否符合用户主观喜好（风格、深度、需求契合度等）",
    explain: {
      title: "偏好匹配度 · Preference",
      rows: [
        { dt: "定义", dd: "风格、深度、需求满足度等偏好维度的平均得分（独立指标）。", tone: "primary" },
        { dt: "范围", dd: "[0, 1]，越高越好" },
      ],
    },
  },
  {
    id: "courseware:reward",
    name: "综合得分",
    expression: "mean(reward)",
    threshold: 0.7,
    unit: "score",
    summary: "综合质量评分（格式 + 内容 + 质量 + 偏好加权平均）",
    explain: {
      title: "综合得分 · Reward",
      rows: [
        { dt: "定义", dd: "归一化到 [0,1] 的综合质量分，融合门控与软/偏好质量。", tone: "primary" },
        { dt: "计算", dd: "(S_format + S_common + S_soft + S_pref) / 4" },
        { dt: "标准", dd: "达标线 ≥ 0.70；综合质量合格。", tone: "success" },
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
