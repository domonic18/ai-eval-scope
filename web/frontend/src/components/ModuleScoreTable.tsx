import { Table } from "antd";

interface ModuleScoreTableProps {
  moduleResults: Record<string, any>;
}

export default function ModuleScoreTable({ moduleResults }: ModuleScoreTableProps) {
  const data = Object.entries(moduleResults).map(([module, result]) => ({
    key: module,
    module,
    passed: result.passed ? "通过" : "未通过",
    score: typeof result.score === "number" ? result.score.toFixed(2) : "—",
    reason: result.reason || "—",
  }));

  const columns = [
    { title: "模块", dataIndex: "module", key: "module" },
    { title: "状态", dataIndex: "passed", key: "passed" },
    { title: "得分", dataIndex: "score", key: "score" },
    { title: "说明", dataIndex: "reason", key: "reason", ellipsis: true },
  ];

  return <Table dataSource={data} columns={columns} pagination={false} />;
}
