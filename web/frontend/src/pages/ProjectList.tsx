import { useEffect, useState } from "react";
import { Button, Col, Row, Spin, Typography, message } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import ProjectCard from "../components/ProjectCard";
import { getProjects, rebuildIndex } from "../api/client";
import type { Project } from "../types";

export default function ProjectList() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  const loadProjects = async () => {
    setLoading(true);
    try {
      const data = await getProjects();
      setProjects(data);
    } catch (err) {
      message.error("加载项目失败");
    } finally {
      setLoading(false);
    }
  };

  const handleRebuild = async () => {
    setRebuilding(true);
    try {
      const res = await rebuildIndex();
      message.success(`索引重建完成：${res.data.project_count} 个项目，${res.data.run_count} 次运行`);
      await loadProjects();
    } catch (err) {
      message.error("索引重建失败");
    } finally {
      setRebuilding(false);
    }
  };

  useEffect(() => {
    loadProjects();
  }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 24 }}>
        <Typography.Title level={2}>项目看板</Typography.Title>
        <Button
          icon={<ReloadOutlined />}
          loading={rebuilding}
          onClick={handleRebuild}
        >
          重建索引
        </Button>
      </div>
      {loading ? (
        <Spin size="large" style={{ display: "block", margin: "48px auto" }} />
      ) : projects.length === 0 ? (
        <Typography.Text type="secondary">暂无项目，请先运行 agent-eval index 重建索引。</Typography.Text>
      ) : (
        <Row gutter={[24, 24]}>
          {projects.map((project) => (
            <Col xs={24} md={12} key={project.id}>
              <ProjectCard project={project} />
            </Col>
          ))}
        </Row>
      )}
    </div>
  );
}
