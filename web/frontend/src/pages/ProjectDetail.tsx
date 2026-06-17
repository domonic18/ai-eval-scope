import { useEffect, useState } from "react";
import { Table, Typography, Card, Button, Space, Modal, Input, App as AntApp, Tag, Popconfirm } from "antd";
import { PlusOutlined, CopyOutlined } from "@ant-design/icons";
import { useParams, useNavigate } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import { api } from "../api/client";
import type { ApiKeySafe, IssuedApiKey, RunSummary, TrendPoint } from "../types";

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const { message } = AntApp.useApp();
  const [runs, setRuns] = useState<{ items: RunSummary[]; total: number } | null>(null);
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [keys, setKeys] = useState<ApiKeySafe[]>([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [issued, setIssued] = useState<IssuedApiKey | null>(null);
  const [creating, setCreating] = useState(false);
  const [projectName, setProjectName] = useState("");

  async function loadKeys() {
    if (!id) return;
    setKeysLoading(true);
    try {
      setKeys(await api.listKeys(id));
    } finally {
      setKeysLoading(false);
    }
  }

  useEffect(() => {
    if (!id) return;
    api.project(id).then((p) => setProjectName(p.name)).catch(() => {});
    api.projectRuns(id).then(setRuns).catch(() => setRuns({ items: [], total: 0 }));
    api.projectTrends(id).then(setTrends).catch(() => setTrends([]));
    loadKeys();
  }, [id]);

  async function doArchive() {
    if (!id) return;
    try {
      await api.archiveProject(id);
      message.success("已归档");
      nav("/");
    } catch (e) {
      message.error("归档失败：" + ((e as Error).message ?? ""));
    }
  }

  async function doCreate() {
    if (!id || !newName.trim()) return;
    setCreating(true);
    try {
      const k = await api.createKey(id, newName.trim());
      setIssued(k);
      setCreateOpen(false);
      setNewName("");
      loadKeys();
    } catch (e) {
      message.error("签发失败：" + ((e as Error).message ?? ""));
    } finally {
      setCreating(false);
    }
  }

  async function doRevoke(keyId: string) {
    if (!id) return;
    try {
      await api.revokeKey(id, keyId);
      message.success("已吊销");
      loadKeys();
    } catch (e) {
      message.error("吊销失败：" + ((e as Error).message ?? ""));
    }
  }

  const chartOption = {
    tooltip: { trigger: "axis" },
    legend: { data: ["DR", "CPR", "Reward"] },
    xAxis: {
      type: "category",
      data: trends.map((t) => new Date(t.created_at).toLocaleString()),
    },
    yAxis: { type: "value", min: 0, max: 1 },
    series: [
      { name: "DR", type: "line", data: trends.map((t) => t.DR), smooth: true },
      { name: "CPR", type: "line", data: trends.map((t) => t.CPR), smooth: true },
      { name: "Reward", type: "line", data: trends.map((t) => t.Reward), smooth: true },
    ],
  };

  return (
    <>
      <Space style={{ justifyContent: "space-between", width: "100%", marginBottom: 8 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {projectName || "项目"}
        </Typography.Title>
        <Popconfirm title="归档此项目？归档后不再在看板显示。" onConfirm={doArchive}>
          <Button danger>归档项目</Button>
        </Popconfirm>
      </Space>

      <Typography.Title level={4}>项目趋势</Typography.Title>
      <Card style={{ marginBottom: 16 }}>
        {trends.length > 0 ? (
          <ReactECharts option={chartOption} style={{ height: 320 }} />
        ) : (
          <Typography.Text type="secondary">暂无运行数据</Typography.Text>
        )}
      </Card>

      <Typography.Title level={4}>运行列表</Typography.Title>
      <Table
        rowKey="id"
        dataSource={runs?.items ?? []}
        loading={runs === null}
        pagination={{ pageSize: 20, total: runs?.total ?? 0 }}
        onRow={(r) => ({ onClick: () => nav(`/run/${r.id}`) })}
        columns={[
          { title: "运行", dataIndex: "externalRunId", key: "externalRunId" },
          { title: "模式", dataIndex: "mode", key: "mode" },
          { title: "状态", dataIndex: "status", key: "status" },
          { title: "DR", key: "dr", render: (_, r) => r.dr.toFixed(3) },
          { title: "CPR", key: "cpr", render: (_, r) => r.cpr.toFixed(3) },
          { title: "Reward", key: "reward", render: (_, r) => r.avgReward.toFixed(3) },
          {
            title: "时间",
            key: "createdAt",
            render: (_, r) => new Date(r.createdAt).toLocaleString(),
          },
        ]}
      />

      <Typography.Title level={4} style={{ marginTop: 24 }}>
        API Keys
      </Typography.Title>
      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            签发新 Key
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            评估器（ResultSink）凭此 Key 的 HMAC 签名摄取数据；secret 仅在签发时显示一次。
          </Typography.Text>
        </Space>
        <Table
          rowKey="id"
          dataSource={keys}
          loading={keysLoading}
          pagination={false}
          columns={[
            { title: "名称", dataIndex: "name", key: "name" },
            { title: "公钥", dataIndex: "publicKey", key: "publicKey", render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
            { title: "调用次数", dataIndex: "callCount", key: "callCount" },
            {
              title: "最近使用",
              key: "lastUsedAt",
              render: (_, r) => (r.lastUsedAt ? new Date(r.lastUsedAt).toLocaleString() : "—"),
            },
            {
              title: "状态",
              key: "status",
              render: (_, r) => (r.revokedAt ? <Tag color="red">已吊销</Tag> : <Tag color="green">有效</Tag>),
            },
            {
              title: "操作",
              key: "op",
              render: (_, r) =>
                r.revokedAt ? null : (
                  <Popconfirm title="确认吊销此 Key？吊销后摄取鉴权立即失败。" onConfirm={() => doRevoke(r.id)}>
                    <Button danger size="small">
                      吊销
                    </Button>
                  </Popconfirm>
                ),
            },
          ]}
        />
      </Card>

      {/* 签发弹窗 */}
      <Modal
        title="签发新 API Key"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={doCreate}
        confirmLoading={creating}
        okText="签发"
      >
        <Input placeholder="Key 名称（如：local-dev / ci）" value={newName} onChange={(e) => setNewName(e.target.value)} />
      </Modal>

      {/* Secret 一次性展示弹窗 */}
      <Modal
        title="API Key 已签发"
        open={!!issued}
        onCancel={() => setIssued(null)}
        okText="我已保存"
        cancelButtonProps={{ style: { display: "none" } }}
        onOk={() => setIssued(null)}
      >
        {issued && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Typography.Text type="warning" strong>
              ⚠️ secret 仅此次显示一次，关闭后无法再查看，请立即保存！
            </Typography.Text>
            <div>
              <Typography.Text type="secondary">公钥（public key）</Typography.Text>
              <Input.Password value={issued.publicKey} readOnly />
            </div>
            <div>
              <Typography.Text type="secondary">密钥（secret key）</Typography.Text>
              <Space.Compact style={{ width: "100%" }}>
                <Input.Password value={issued.secretKey} readOnly />
                <Button
                  icon={<CopyOutlined />}
                  onClick={async () => {
                    await navigator.clipboard.writeText(issued.secretKey);
                    message.success("已复制 secret");
                  }}
                >
                  复制
                </Button>
              </Space.Compact>
            </div>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
              评估器侧配置：<code>AGENT_EVAL_PUBLIC_KEY</code> / <code>AGENT_EVAL_SECRET_KEY</code>
            </Typography.Paragraph>
          </Space>
        )}
      </Modal>
    </>
  );
}
