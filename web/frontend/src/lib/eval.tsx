/** 评估语义常量与指标说明文案（对齐 docs/design 原型）。 */
import type { ReactNode } from "react"

/** 约束层级 tier → chip 语义色（hard/soft/pref）。 */
export type TierChip = "hard" | "soft" | "pref"

export function tierToChip(tier: string): TierChip {
  if (tier === "hard_gate" || tier === "hard_score") return "hard"
  if (tier === "soft") return "soft"
  return "pref"
}

export const TIER_LABEL: Record<string, string> = {
  hard_gate: "HARD_GATE",
  hard_score: "HARD_SCORE",
  soft: "SOFT",
  preference: "PREFERENCE",
}

/** 阶段定义：约束按 tier 归入 format / commonsense / quality。 */
export interface StageDef {
  key: string
  title: string
  /** 阶段左侧色条颜色变量名。 */
  bar: string
  /** 归入该阶段的 tier 集合。 */
  tiers: string[]
  /** 阶段头展示的 chip。 */
  chips: { chip: TierChip; label: string }[]
  /** 该阶段的得分说明 key（用于 ? 说明）。 */
  scoreExplainKey?: "S_format" | "S_common" | "S_soft_pref"
  /** 阶段头得分文案，传入样本阶段分。 */
  scoreText?: (s: {
    sFormat?: number
    sCommon?: number
    sSoft?: number
    sPref?: number
  }) => ReactNode
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
]

function fmt1(n: number | undefined): string {
  return n == null ? "—" : n.toFixed(2)
}
/** format 阶段：1.00 绿 / -3 红；其它：0 红 / 1 绿。 */
function colorOf(n: number | undefined, isFormat: boolean): string {
  if (n == null) return "var(--text-secondary)"
  if (isFormat) return n >= 1 ? "var(--success)" : "var(--danger)"
  return n >= 1 ? "var(--success)" : n <= 0 ? "var(--danger)" : "var(--warning)"
}

/** 核心指标阈值。 */
export const THRESHOLDS = {
  DR: 0.95,
  CPR: 0.9,
  Reward: 0.8,
  Soft: 0.7,
  Pref: 0.7,
}

export type MetricKey = "DR" | "CPR" | "Reward" | "Soft" | "Pref" | "CondR"

export interface ExplainRow {
  dt: string
  dd: ReactNode
}
export interface ExplainContent {
  title: ReactNode
  rows: ExplainRow[]
}

export const METRIC_LABEL: Record<MetricKey, string> = {
  DR: "交付率(DR)",
  CPR: "约束通过率(CPR)",
  Reward: "综合评分(Reward)",
  Soft: "内容质量分(Soft)",
  Pref: "用户偏好分(Pref)",
  CondR: "条件Reward(CondR)",
}

export const METRIC_EXPLAIN: Record<MetricKey, ExplainContent> = {
  DR: {
    title: (
      <>
        DR · Delivery Rate <code className="code-inline">交付率</code>
      </>
    ),
    rows: [
      {
        dt: "定义",
        dd: (
          <>
            <b style={{ color: "var(--text-primary)" }}>能正常打开、格式符合基本要求</b>的样本占多少——连格式都不对，就没法使用了。
          </>
        ),
      },
      { dt: "计算", dd: <span className="mono">格式合格的样本数 ÷ 全部样本数</span> },
      {
        dt: "标准",
        dd: (
          <>
            达标线 <span className="mono">≥ {THRESHOLDS.DR}</span>（即 {Math.round(THRESHOLDS.DR * 100)}%）；低于则这批整体不合格。
          </>
        ),
      },
    ],
  },
  CPR: {
    title: (
      <>
        CPR · Constraint Pass Rate <code className="code-inline">约束通过率</code>
      </>
    ),
    rows: [
      {
        dt: "定义",
        dd: (
          <>
            <b style={{ color: "var(--text-primary)" }}>格式合格、并且内容也正确</b>（没有事实或常识错误）的样本占多少。
          </>
        ),
      },
      { dt: "计算", dd: <span className="mono">格式和内容都通过的样本数 ÷ 全部样本数</span> },
      {
        dt: "标准",
        dd: (
          <>
            达标线 <span className="mono">≥ {THRESHOLDS.CPR}</span>（即 {Math.round(THRESHOLDS.CPR * 100)}%）。
          </>
        ),
      },
    ],
  },
  Reward: {
    title: (
      <>
        Reward <code className="code-inline">综合评分</code>
      </>
    ),
    rows: [
      {
        dt: "定义",
        dd: (
          <>
            每个样本的整体质量分，取值 <b style={{ color: "var(--text-primary)" }}>0~1</b>，综合
            <b style={{ color: "var(--text-primary)" }}>格式、内容正确性、内容质量、用户喜好</b>四个方面。
          </>
        ),
      },
      {
        dt: "计算",
        dd: (
          <>
            <div className="mono" style={{ margin: "4px 0 6px" }}>
              综合得分 =（格式分 + 内容正确性分 + 内容质量分 + 用户喜好分）÷ 4
            </div>
            四个方面<b>各占 25%（等权）</b>，每项 0~1 分；满分 <span className="mono">1.0</span>，
            <b style={{ color: "var(--danger)" }}>格式不合格则整体直接算 0 分</b>；最后取该项目所有样本的平均。
          </>
        ),
      },
      {
        dt: "标准",
        dd: (
          <>
            达标阈值 <span className="mono">≥ {THRESHOLDS.Reward}</span>（即{" "}
            {Math.round((THRESHOLDS.Reward ?? 0) * 100)}% 质量）；越高越好。
          </>
        ),
      },
    ],
  },
  Soft: {
    title: (
      <>
        Soft <code className="code-inline">内容质量分</code>
      </>
    ),
    rows: [
      {
        dt: "定义",
        dd: (
          <>
            <b style={{ color: "var(--text-primary)" }}>内容本身的质量</b>打分（结构、逻辑、多样性、可读性等），取值 0~1。
          </>
        ),
      },
      {
        dt: "计算",
        dd: <>由若干"内容质量"评估器（如教学逻辑、内容多样性）各自打分后<b>加权平均</b>。</>,
      },
      {
        dt: "标准",
        dd: (
          <>
            达标线 <span className="mono">≥ {THRESHOLDS.Soft}</span>（即 {Math.round(THRESHOLDS.Soft * 100)}%）；不影响是否"通过"，只反映质量高低。
          </>
        ),
      },
    ],
  },
  Pref: {
    title: (
      <>
        Pref <code className="code-inline">用户偏好分</code>
      </>
    ),
    rows: [
      {
        dt: "定义",
        dd: (
          <>
            <b style={{ color: "var(--text-primary)" }}>是否符合用户主观喜好</b>（风格、深度、需求契合度等），取值 0~1。
          </>
        ),
      },
      {
        dt: "计算",
        dd: <>由若干"偏好"评估器（如风格、深度、需求满足）各自打分后<b>加权平均</b>。</>,
      },
      {
        dt: "标准",
        dd: (
          <>
            达标线 <span className="mono">≥ {THRESHOLDS.Pref}</span>（即 {Math.round(THRESHOLDS.Pref * 100)}%）；主观维度，越高越贴合用户预期。
          </>
        ),
      },
    ],
  },
  CondR: {
    title: (
      <>
        CondR · Conditional Reward <code className="code-inline">达标综合分</code>
      </>
    ),
    rows: [
      {
        dt: "定义",
        dd: (
          <>
            <b style={{ color: "var(--text-primary)" }}>同时通过格式与常识门禁</b>的样本的平均
            Reward，排除「直接判负」样本的干扰。
          </>
        ),
      },
      { dt: "计算", dd: <span className="mono">Σ Reward(已过门禁) / 已过门禁样本数</span> },
      { dt: "用途", dd: <>反映「合格产物」的真实质量上限。</> },
    ],
  },
}

/** 阶段得分 ? 说明。 */
export const SCORE_EXPLAIN: Record<"S_format" | "S_common" | "S_soft_pref", ExplainContent> = {
  S_format: {
    title: (
      <>
        S_format <code className="code-inline">格式得分</code>
      </>
    ),
    rows: [
      {
        dt: "层级",
        dd: (
          <>
            <span className="chip chip-hard">HARD_GATE</span> 硬门禁，失败即
            fail-fast，后续阶段跳过。
          </>
        ),
      },
      {
        dt: "取值",
        dd: (
          <>
            全部格式约束通过 = <span className="mono">+1.00</span>；任一失败 ={" "}
            <span className="mono">-3.00</span>（直接判负）。
          </>
        ),
      },
    ],
  },
  S_common: {
    title: (
      <>
        S_common <code className="code-inline">常识得分</code>
      </>
    ),
    rows: [
      {
        dt: "层级",
        dd: (
          <>
            <span className="chip chip-hard">HARD_SCORE</span>{" "}
            硬约束，失败不中断同阶段其它评估器，但标记门禁未过。
          </>
        ),
      },
      {
        dt: "取值",
        dd: (
          <>
            全部常识约束通过 = <span className="mono">+1.00</span>；任一失败 ={" "}
            <span className="mono">0.00</span>。
          </>
        ),
      },
    ],
  },
  S_soft_pref: {
    title: (
      <>
        S_soft / S_pref <code className="code-inline">质量得分</code>
      </>
    ),
    rows: [
      {
        dt: "S_soft",
        dd: (
          <>
            <span className="chip chip-soft">SOFT</span>{" "}
            软约束（如教学逻辑、内容多样性）加权平均，归一化到 <span className="mono">[0,1]</span>。
          </>
        ),
      },
      {
        dt: "S_pref",
        dd: (
          <>
            <span className="chip chip-pref">PREFERENCE</span>{" "}
            偏好约束（风格、深度、需求满足）加权平均，归一化到 <span className="mono">[0,1]</span>。
          </>
        ),
      },
      {
        dt: "作用",
        dd: (
          <>
            不影响门禁，按权重计入最终 <span className="mono">Reward</span>。
          </>
        ),
      },
    ],
  },
}

/** 指标值根据阈值着色：达标绿 / 未达红 / 中性。 */
export function metricColor(key: MetricKey, value: number | null | undefined): string {
  if (value == null) return "var(--text-primary)"
  const thr = THRESHOLDS[key as "DR" | "CPR" | "Reward" | "Soft" | "Pref"]
  if (thr == null) return "var(--accent)"
  if (value >= thr) return "var(--success)"
  return "var(--warning)"
}

/** 运行状态 → 徽章 meta。 */
export function runBadge(status: string): {
  variant: "success" | "warning" | "danger" | "info" | "neutral"
  dot?: string
  pulse?: boolean
  label: string
} {
  switch (status) {
    case "completed":
      return { variant: "success", label: "completed" }
    case "running":
      return { variant: "info", dot: "var(--info)", pulse: true, label: "running" }
    case "partial":
      return { variant: "warning", label: "partial" }
    case "failed":
      return { variant: "danger", label: "failed" }
    default:
      return { variant: "neutral", label: status || "—" }
  }
}

/** 样本状态 → 徽章 meta。 */
export function sampleBadge(status: string): {
  variant: "success" | "warning" | "danger" | "info" | "neutral"
  label: string
} {
  switch (status) {
    case "pass":
    case "passed":
      return { variant: "success", label: "pass" }
    case "fail":
    case "failed":
      return { variant: "danger", label: "fail" }
    case "skip":
    case "skipped":
      return { variant: "warning", label: "skip" }
    default:
      return { variant: "neutral", label: status || "—" }
  }
}
