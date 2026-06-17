import { useEffect, useState } from "react";
import { Button, Card, Col, Empty, Form, Input, Modal, Row, Skeleton, Space, Statistic, Tag, Typography, App as AntApp } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useOutletContext, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { DashboardProject } from "../types";

function pct(n: number | null | undefined): string {
  return n == null ? "—" : (n * 100).toFixed(1) + "%";
}

export default function Dashboard() {
  const { activeOrg } = useOutletContext<{ activeOrg: string | null }>();
  const nav = useNavigate();
  const { message } = AntApp.useApp();
  const [projects, setProjects] = useState<DashboardProject[] | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<{ name: string; slug: string }>();

  async function load() {
    if (!activeOrg) return;
    setProjects(null);
    try {
      setProjects(await api.dashboard(activeOrg));
    } catch {
      setProjects([]);
    }
  }

  useEffect(() => {
    load();
  }, [activeOrg]);

  async function doCreate() {
    const v = await form.validateFields();
    setCreating(true);
    try {
      await api.createProject(activeOrg!, v.name, v.slug);
      message.success("项目已创建");
      setCreateOpen(false);
      form.resetFields();
      load();
    } catch (e) {
      message.error("创建失败：" + ((e as Error).message ?? ""));
    } finally {
      setCreating(false);
    }
  }

  if (!activeOrg) return <Typography.Text type="secondary">未选择组织</Typography.Text>;
  if (projects === null) return <Skeleton active />;

  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: "space-between", width: "100%" }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          项目看板
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建项目
        </Button>
      </Space>

      {projects.length === 0 ? (
        <Empty description="该组织下暂无项目，点击右上角「新建项目」创建">
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            新建项目
          </Button>
        </Empty>
      ) : (
        <Row gutter={[16, 16]}>
          {projects.map((p) => (
            <Col xs={24} sm={12} lg={8} key={p.id}>
              <Card hoverable title={p.name} extra={<Tag>{p.slug}</Tag>} onClick={() => nav(`/project/${p.id}`)}>
                <Typography.Paragraph type="secondary" style={{ minHeight: 22 }}>
                  {p.description || "—"}
                </Typography.Paragraph>
                <Row gutter={16}>
                  <Col span={8}>
                    <Statistic title="运行数" value={p.runCount} />
                  </Col>
                  <Col span={8}>
                    <Statistic title="最新 DR" value={pct(p.latestRun?.dr)} />
                  </Col>
                  <Col span={8}>
                    <Statistic title="最新 Reward" value={pct(p.latestRun?.avgReward)} />
                  </Col>
                </Row>
                {p.latestRun && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    最近运行：{new Date(p.latestRun.createdAt || "").toLocaleString()}
                  </Typography.Text>
                )}
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title="新建项目"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={doCreate}
        confirmLoading={creating}
        okText="创建"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true }]}>
            <Input placeholder="如：课件生成评估" />
          </Form.Item>
          <Form.Item name="slug" label="slug（组织内唯一）" rules={[{ required: true }]}>
            <Input placeholder="如：courseware" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

