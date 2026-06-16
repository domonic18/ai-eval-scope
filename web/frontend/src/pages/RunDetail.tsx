import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Breadcrumb,
  Card,
  Col,
  Row,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import StatCard from "../components/StatCard";
import { getRun, getRunTasks } from "../api/client";
import type { RunSummary } from "../types";

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunSummary | null>(null);
  const [tasks, setTasks] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    const load = async () => {
      setLoading(true);
      try {
        const [r, t] = await Promise.all([getRun(id), getRunTasks(id)]);
        setRun(r);
        setTasks(t);
      } catch (err) {
        message.error("加载运行详情失败");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id]);

  if (loading) {
    return <Spin size="large" style={{ display: "block", margin: "48px auto" }} />;
  }

  if (!run) {
    return <Typography.Text type="danger">运行不存在</Typography.Text>;
  }

  const metrics = run.metrics;
  const thresholds = run.thresholds || {};

  const taskColumns = [
    {
      title: "任务 ID",
      dataIndex: "taskId",
      key: "taskId",
      render: (taskId: string) => (
        <Link to={`/run/${id}/task/${taskId}`}>{taskId}</Link>
      ),
    },
  ];

  const taskData = tasks.map((taskId) => ({ key: taskId, taskId }));

  return (
    <div>
      <Breadcrumb style={{ marginBottom: 16 }}>
        <Breadcrumb.Item>
          <Link to="/">项目看板</Link>
        </Breadcrumb.Item>
        <Breadcrumb.Item>运行详情</Breadcrumb.Item>
        <Breadcrumb.Item>{run.run_id}</Breadcrumb.Item>
      </Breadcrumb>

      <Typography.Title level={2}>运行详情: {run.run_id}</Typography.Title>
      <Typography.Paragraph>样本总数: {run.total_samples}</Typography.Paragraph>

      <Row gutter={[24, 24]} style={{ marginBottom: 24 }}>
        <Col xs={24} md={8}>
          <StatCard
            title="DR (交付率)"
            value={metrics.DR}
            valueStyle={{
              color: thresholds.DR?.status === "BELOW" ? "#cf1322" : "#3f8600",
            }}
          />
        </Col>
        <Col xs={24} md={8}>
          <StatCard
            title="CPR (约束通过率)"
            value={metrics.CPR}
            valueStyle={{
              color: thresholds.CPR?.status === "BELOW" ? "#cf1322" : "#3f8600",
            }}
          />
        </Col>
        <Col xs={24} md={8}>
          <StatCard
            title="Avg Reward"
            value={metrics.avg_reward}
            valueStyle={{
              color: thresholds.reward?.status === "BELOW" ? "#cf1322" : "#3f8600",
            }}
          />
        </Col>
      </Row>

      {run.failure_breakdown && Object.keys(run.failure_breakdown).length > 0 && (
        <Card title="失败项明细" style={{ marginBottom: 24 }}>
          <Space wrap>
            {Object.entries(run.failure_breakdown).map(([cid, count]) => (
              <Tag color="red" key={cid}>
                {cid}: {count}
              </Tag>
            ))}
          </Space>
        </Card>
      )}

      <Card title="任务结果">
        <Table dataSource={taskData} columns={taskColumns} pagination={false} />
      </Card>
    </div>
  );
}
