import { Card, Space, Tag, Typography } from "antd";
import { Link } from "react-router-dom";
import type { Project } from "../types";
import StatCard from "./StatCard";

interface ProjectCardProps {
  project: Project;
}

export default function ProjectCard({ project }: ProjectCardProps) {
  const latest = project.latest_run;
  return (
    <Link to={`/project/${project.id}`} style={{ textDecoration: "none" }}>
      <Card
        hoverable
        title={
          <Space>
            <span>{project.name}</span>
            <Tag color="blue">{project.run_count} 次运行</Tag>
          </Space>
        }
      >
        <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }}>
          {project.description || "暂无描述"}
        </Typography.Paragraph>
        {latest ? (
          <Space size="large" wrap>
            <StatCard title="DR" value={latest.dr} />
            <StatCard title="CPR" value={latest.cpr} />
            <StatCard title="Avg Reward" value={latest.avg_reward} />
          </Space>
        ) : (
          <Typography.Text type="secondary">暂无运行数据</Typography.Text>
        )}
      </Card>
    </Link>
  );
}
