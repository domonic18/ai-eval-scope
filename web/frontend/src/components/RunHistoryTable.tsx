import { Table, Tag } from "antd";
import { Link } from "react-router-dom";
import type { RunIndexEntry } from "../types";

interface RunHistoryTableProps {
  runs: RunIndexEntry[];
}

export default function RunHistoryTable({ runs }: RunHistoryTableProps) {
  const columns = [
    {
      title: "运行 ID",
      dataIndex: "run_id",
      key: "run_id",
      render: (runId: string) => <Link to={`/run/${runId}`}>{runId}</Link>,
    },
    {
      title: "时间",
      dataIndex: "created_at",
      key: "created_at",
      render: (ts: string) => (ts ? new Date(ts).toLocaleString("zh-CN") : "—"),
    },
    {
      title: "模式",
      dataIndex: "mode",
      key: "mode",
      render: (mode: string) => <Tag>{mode}</Tag>,
    },
    {
      title: "样本数",
      dataIndex: "total_samples",
      key: "total_samples",
    },
    {
      title: "DR",
      dataIndex: ["metrics", "DR"],
      key: "dr",
      render: (v: number) => (v !== undefined ? v.toFixed(3) : "—"),
    },
    {
      title: "CPR",
      dataIndex: ["metrics", "CPR"],
      key: "cpr",
      render: (v: number) => (v !== undefined ? v.toFixed(3) : "—"),
    },
    {
      title: "Avg Reward",
      dataIndex: ["metrics", "avg_reward"],
      key: "avg_reward",
      render: (v: number) => (v !== undefined ? v.toFixed(3) : "—"),
    },
  ];

  return (
    <Table
      dataSource={runs}
      columns={columns}
      rowKey="run_id"
      pagination={{ pageSize: 10 }}
    />
  );
}
