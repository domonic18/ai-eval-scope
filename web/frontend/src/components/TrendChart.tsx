import ReactECharts from "echarts-for-react";
import type { TrendData } from "../types";

interface TrendChartProps {
  trends: TrendData;
}

export default function TrendChart({ trends }: TrendChartProps) {
  const times = trends.data_points.map((p) =>
    new Date(p.created_at).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    })
  );

  const option = {
    title: {
      text: "指标趋势",
      left: "center",
    },
    tooltip: {
      trigger: "axis",
    },
    legend: {
      data: trends.metrics,
      bottom: 0,
    },
    grid: {
      left: "3%",
      right: "4%",
      bottom: "15%",
      containLabel: true,
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: times,
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 1.2,
    },
    series: [
      {
        name: "DR",
        type: "line",
        data: trends.data_points.map((p) => p.DR),
        markLine: trends.thresholds.DR
          ? {
              data: [{ yAxis: trends.thresholds.DR, name: "DR 阈值" }],
              lineStyle: { type: "dashed" },
            }
          : undefined,
      },
      {
        name: "CPR",
        type: "line",
        data: trends.data_points.map((p) => p.CPR),
        markLine: trends.thresholds.CPR
          ? {
              data: [{ yAxis: trends.thresholds.CPR, name: "CPR 阈值" }],
              lineStyle: { type: "dashed" },
            }
          : undefined,
      },
      {
        name: "Reward",
        type: "line",
        data: trends.data_points.map((p) => p.Reward),
        markLine: trends.thresholds.Reward
          ? {
              data: [{ yAxis: trends.thresholds.Reward, name: "Reward 阈值" }],
              lineStyle: { type: "dashed" },
            }
          : undefined,
      },
    ],
  };

  return <ReactECharts option={option} style={{ height: 400 }} />;
}
