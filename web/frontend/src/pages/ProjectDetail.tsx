import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Breadcrumb, Card, Spin, Typography, message } from "antd";
import TrendChart from "../components/TrendChart";
import RunHistoryTable from "../components/RunHistoryTable";
import { getProject, getProjectRuns, getProjectTrends } from "../api/client";
import type { Project, RunIndexEntry, TrendData } from "../types";

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [runs, setRuns] = useState<RunIndexEntry[]>([]);
  const [trends, setTrends] = useState<TrendData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    const load = async () => {
      setLoading(true);
      try {
        const [p, r, t] = await Promise.all([
          getProject(id),
          getProjectRuns(id),
          getProjectTrends(id),
        ]);
        setProject(p);
        setRuns(r);
        setTrends(t);
      } catch (err) {
        message.error("加载项目详情失败");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id]);

  if (loading) {
    return <Spin size="large" style={{ display: "block", margin: "48px auto" }} />;
  }

  if (!project) {
    return <Typography.Text type="danger">项目不存在</Typography.Text>;
  }

  return (
    <div>
      <Breadcrumb style={{ marginBottom: 16 }}>
        <Breadcrumb.Item>
          <Link to="/">项目看板</Link>
        </Breadcrumb.Item>
        <Breadcrumb.Item>{project.name}</Breadcrumb.Item>
      </Breadcrumb>

      <Typography.Title level={2}>{project.name}</Typography.Title>
      <Typography.Paragraph>{project.description || "暂无描述"}</Typography.Paragraph>

      {trends && trends.data_points.length > 0 && (
        <Card title="指标趋势" style={{ marginBottom: 24 }}>
          <TrendChart trends={trends} />
        </Card>
      )}

      <Card title="运行历史">
        <RunHistoryTable runs={runs} />
      </Card>
    </div>
  );
}
