import { Card, Statistic } from "antd";

interface StatCardProps {
  title: string;
  value: number;
  suffix?: string;
  precision?: number;
  valueStyle?: React.CSSProperties;
}

export default function StatCard({
  title,
  value,
  suffix,
  precision = 2,
  valueStyle,
}: StatCardProps) {
  return (
    <Card>
      <Statistic
        title={title}
        value={value}
        precision={precision}
        suffix={suffix}
        valueStyle={valueStyle}
      />
    </Card>
  );
}
