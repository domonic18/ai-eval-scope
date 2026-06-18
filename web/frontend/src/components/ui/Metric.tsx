import type { ReactNode } from "react";
import { Explain } from "./Explain";
import type { ExplainContent } from "../../lib/eval";

/** 阈值对照 gauge 条：value/threshold 为 0~1。 */
export function Gauge({
  value,
  threshold,
  color = "var(--accent)",
}: {
  value: number; // 0~1
  threshold?: number; // 0~1
  color?: string;
}) {
  return (
    <div className="gauge">
      <span className="gauge-fill" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color }} />
      {threshold != null && <span className="gauge-thresh" style={{ left: `${Math.max(0, Math.min(1, threshold)) * 100}%` }} />}
    </div>
  );
}

/** 指标卡 .metric：标签 + 等宽大数字 + (可选)阈值 gauge + Explain + 环比。 */
export function Metric({
  label,
  value,
  valueColor,
  explain,
  badge,
  gauge,
  foot,
}: {
  label: ReactNode;
  value: ReactNode;
  valueColor?: string;
  explain?: ExplainContent;
  badge?: ReactNode;
  gauge?: ReactNode;
  foot?: ReactNode;
}) {
  return (
    <div className="metric">
      <div className="metric-top">
        <span className="row" style={{ gap: 0 }}>
          <span className="metric-label">{label}</span>
          {explain && <Explain content={explain} />}
        </span>
        {badge}
      </div>
      <div className="metric-value" style={valueColor ? { color: valueColor } : undefined}>
        {value}
      </div>
      {gauge}
      {foot && <div className="metric-foot">{foot}</div>}
    </div>
  );
}
