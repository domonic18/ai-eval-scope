/** 评估语义常量与指标说明文案（对齐 docs/design 原型）。 */
import type { ReactNode } from "react";

/** 约束层级 tier → chip 语义色（hard/soft/pref）。 */
export type TierChip = "hard" | "soft" | "pref";

export function tierToChip(tier: string): TierChip {
  if (tier === "hard_gate" || tier === "hard_score") return "hard";
  if (tier === "soft") return "soft";
  return "pref";
}

export const TIER_LABEL: Record<string, string> = {
  hard_gate: "HARD_GATE",
  hard_score: "HARD_SCORE",
  soft: "SOFT",
  preference: "PREFERENCE",
};

/** 阶段定义：约束按 tier 归入 format / commonsense / quality。 */
export interface StageDef {
  key: string;
  title: string;
  /** 阶段左侧色条颜色变量名。 */
  bar: string;
  /** 归入该阶段的 tier 集合。 */
  tiers: string[];
  /** 阶段头展示的 chip。 */
  chips: { chip: TierChip; label: string }[];
  /** 该阶段的得分说明 key（用于 ? 说明）。 */
  scoreExplainKey?: "S_format" | "S_common" | "S_soft_pref";
  /** 阶段头得分文案，传入样本阶段分。 */
  scoreText?: (s: { sFormat?: number; sCommon?: number; sSoft?: number; sPref?: number }) => ReactNode;
}

export const STAGES: StageDef[] = [
  {
    key: "format",
    title: "格式 Format",
    bar: "var(--success)",
    tiers: ["hard_gate"],
    chips: [{ chip: "hard", label: "HARD_GATE" }],
    scoreExplainKey: "S_format",
    scoreText: (s) => (
      <>
        S_format = <b style={{ color: colorOf(s.sFormat, true) }}>{fmt1(s.sFormat)}</b>
      </>
    ),
  },
  {
    key: "commonsense",
    title: "常识 Commonsense",
    bar: "var(--danger)",
    tiers: ["hard_score"],
    chips: [{ chip: "hard", label: "HARD_SCORE" }],
    scoreExplainKey: "S_common",
    scoreText: (s) => (
      <>
        S_common = <b style={{ color: colorOf(s.sCommon, false) }}>{fmt1(s.sCommon)}</b>
      </>
    ),
  },
  {
    key: "quality",
    title: "质量 Quality",
    bar: "var(--warning)",
    tiers: ["soft", "preference"],
    chips: [
      { chip: "soft", label: "SOFT" },
      { chip: "pref", label: "PREFERENCE" },
    ],
    scoreExplainKey: "S_soft_pref",
    scoreText: (s) => (
      <>
        S_soft <b>{fmt1(s.sSoft)}</b> · S_pref <b>{fmt1(s.sPref)}</b>
      </>
    ),
  },
];

function fmt1(n: number | undefined): string {
  return n == null ? "—" : n.toFixed(2);
}
/** format 阶段：1.00 绿 / -3 红；其它：0 红 / 1 绿。 */
function colorOf(n: number | undefined, isFormat: boolean): string {
  if (n == null) return "var(--text-secondary)";
  if (isFormat) return n >= 1 ? "var(--success)" : "var(--danger)";
  return n >= 1 ? "var(--success)" : n <= 0 ? "var(--danger)" : "var(--warning)";
}

/** 核心指标阈值。 */
export const THRESHOLDS = {
  DR: 0.95,
  CPR: 0.9,
  Reward: 0.8,
};

export type MetricKey = "DR" | "CPR" | "Reward" | "CondR";

export interface ExplainRow {
  dt: string;
  dd: ReactNode;
}
export interface ExplainContent {
  title: ReactNode;
  rows: ExplainRow[];
}

export const METRIC_LABEL: Record<MetricKey, string> = {
  DR: "DR 交付率",
  CPR: "CPR 常识",
  Reward: "Reward",
  CondR: "CondR 条件",
};

export const METRIC_EXPLAIN: Record<MetricKey, ExplainContent> = {
  DR: {
    title: (
      <>
        DR · Delivery Rate <code className="code-inline">交付率</code>
      </>
    ),
    rows: [
      { dt: "定义", dd: <>通过<b style={{ color: "var(--text-primary)" }}>格式硬门禁</b>的样本占比，衡量产物能否被正常交付。</> },
      { dt: "计算", dd: <span className="mono">格式通过样本数 / 总样本数</span> },
      { dt: "标准", dd: <>达标阈值 <span className="mono">≥ {THRESHOLDS.DR}</span>；低于即判定该运行不达标。</> },
    ],
  },
  CPR: {
    title: (
      <>
        CPR · Commonsense Pass Rate <code className="code-inline">常识通过率</code>
      </>
    ),
    rows: [
      { dt: "定义", dd: <>通过<b style={{ color: "var(--text-primary)" }}>常识硬约束</b>（史实、数理、单位、逻辑等）的样本占比。</> },
      { dt: "计算", dd: <span className="mono">常识通过样本数 / 总样本数</span> },
      { dt: "标准", dd: <>达标阈值 <span className="mono">≥ {THRESHOLDS.CPR}</span>。</> },
    ],
  },
  Reward: {
    title: (
      <>
        Reward <code className="code-inline">综合奖励</code>
      </>
    ),
    rows: [
      { dt: "定义", dd: <>样本综合得分，聚合四个阶段得分的加权和。</> },
      { dt: "计算", dd: <><span className="mono">S_format + S_common + w₃·S_soft + w₄·S_pref</span> 后对全部样本取均值。</> },
      { dt: "标准", dd: <>达标阈值 <span className="mono">≥ {THRESHOLDS.Reward}</span>；反映整体质量水位。</> },
    ],
  },
  CondR: {
    title: (
      <>
        CondR · Conditional Reward <code className="code-inline">条件奖励</code>
      </>
    ),
    rows: [
      { dt: "定义", dd: <><b style={{ color: "var(--text-primary)" }}>同时通过格式与常识门禁</b>的样本的平均 Reward，排除「直接判负」样本的干扰。</> },
      { dt: "计算", dd: <span className="mono">Σ Reward(已过门禁) / 已过门禁样本数</span> },
      { dt: "用途", dd: <>反映「合格产物」的真实质量上限。</> },
    ],
  },
};

/** 阶段得分 ? 说明。 */
export const SCORE_EXPLAIN: Record<"S_format" | "S_common" | "S_soft_pref", ExplainContent> = {
  S_format: {
    title: (
      <>
        S_format <code className="code-inline">格式得分</code>
      </>
    ),
    rows: [
      { dt: "层级", dd: <><span className="chip chip-hard">HARD_GATE</span> 硬门禁，失败即 fail-fast，后续阶段跳过。</> },
      { dt: "取值", dd: <>全部格式约束通过 = <span className="mono">+1.00</span>；任一失败 = <span className="mono">-3.00</span>（直接判负）。</> },
    ],
  },
  S_common: {
    title: (
      <>
        S_common <code className="code-inline">常识得分</code>
      </>
    ),
    rows: [
      { dt: "层级", dd: <><span className="chip chip-hard">HARD_SCORE</span> 硬约束，失败不中断同阶段其它评估器，但标记门禁未过。</> },
      { dt: "取值", dd: <>全部常识约束通过 = <span className="mono">+1.00</span>；任一失败 = <span className="mono">0.00</span>。</> },
    ],
  },
  S_soft_pref: {
    title: (
      <>
        S_soft / S_pref <code className="code-inline">质量得分</code>
      </>
    ),
    rows: [
      { dt: "S_soft", dd: <><span className="chip chip-soft">SOFT</span> 软约束（如教学逻辑、内容多样性）加权平均，归一化到 <span className="mono">[0,1]</span>。</> },
      { dt: "S_pref", dd: <><span className="chip chip-pref">PREFERENCE</span> 偏好约束（风格、深度、需求满足）加权平均，归一化到 <span className="mono">[0,1]</span>。</> },
      { dt: "作用", dd: <>不影响门禁，按权重计入最终 <span className="mono">Reward</span>。</> },
    ],
  },
};

/** 指标值根据阈值着色：达标绿 / 未达红 / 中性。 */
export function metricColor(key: MetricKey, value: number | null | undefined): string {
  if (value == null) return "var(--text-primary)";
  const thr = THRESHOLDS[key as "DR" | "CPR" | "Reward"];
  if (thr == null) return "var(--accent)";
  if (value >= thr) return key === "Reward" || key === "DR" ? "var(--success)" : "var(--signal)";
  return "var(--warning)";
}

/** 运行状态 → 徽章 meta。 */
export function runBadge(status: string): {
  variant: "success" | "warning" | "danger" | "info" | "neutral";
  dot?: string;
  pulse?: boolean;
  label: string;
} {
  switch (status) {
    case "completed":
      return { variant: "success", label: "completed" };
    case "running":
      return { variant: "info", dot: "var(--info)", pulse: true, label: "running" };
    case "partial":
      return { variant: "warning", label: "partial" };
    case "failed":
      return { variant: "danger", label: "failed" };
    default:
      return { variant: "neutral", label: status || "—" };
  }
}

/** 样本状态 → 徽章 meta。 */
export function sampleBadge(status: string): {
  variant: "success" | "warning" | "danger" | "info" | "neutral";
  label: string;
} {
  switch (status) {
    case "pass":
    case "passed":
      return { variant: "success", label: "pass" };
    case "fail":
    case "failed":
      return { variant: "danger", label: "fail" };
    case "skip":
    case "skipped":
      return { variant: "warning", label: "skip" };
    default:
      return { variant: "neutral", label: status || "—" };
  }
}
