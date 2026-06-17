import { useEffect, useState } from "react";
import { Button, Descriptions, Space, Table, Tag, Typography } from "antd";
import { LinkOutlined } from "@ant-design/icons";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api/client";

interface RunDetailData {
  id: string;
  externalRunId: string;
  mode: string;
  status: string;
  totalSamples: number;
  dr: number;
  cpr: number;
  avgReward: number;
  condR: number;
  avgTimeMs: number;
  ruleSetVersion: string | null;
  langfuseTraceId: string | null;
  langfuseHost: string | null;
  createdAt: string;
  samples: Array<{
    id: string;
    externalSampleId: string;
    status: string;
    reward: number;
    sFormat: number;
    sCommon: number;
    sSoft: number;
    sPref: number;
  }>;
}

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [run, setRun] = useState<RunDetailData | null>(null);

  useEffect(() => {
    if (!id) return;
    api.runDetail(id).then(setRun).catch(() => setRun(null));
  }, [id]);

  if (!run) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  const langfuseUrl =
    run.langfuseTraceId && run.langfuseHost
      ? `${run.langfuseHost}/trace/${run.langfuseTraceId}`
      : null;

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          运行 {run.externalRunId}
        </Typography.Title>
        <Tag>{run.status}</Tag>
        {langfuseUrl && (
          <Button size="small" icon={<LinkOutlined />} href={langfuseUrl} target="_blank">
            在 Langfuse 查看
          </Button>
        )}
      </Space>

      <Descriptions bordered size="small" column={3} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="模式">{run.mode}</Descriptions.Item>
        <Descriptions.Item label="样本数">{run.totalSamples}</Descriptions.Item>
        <Descriptions.Item label="规则集版本">{run.ruleSetVersion ?? "—"}</Descriptions.Item>
        <Descriptions.Item label="DR">{run.dr.toFixed(3)}</Descriptions.Item>
        <Descriptions.Item label="CPR">{run.cpr.toFixed(3)}</Descriptions.Item>
        <Descriptions.Item label="Reward">{run.avgReward.toFixed(3)}</Descriptions.Item>
        <Descriptions.Item label="CondR">{run.condR.toFixed(3)}</Descriptions.Item>
        <Descriptions.Item label="平均耗时">{run.avgTimeMs.toFixed(0)}ms</Descriptions.Item>
        <Descriptions.Item label="时间">{new Date(run.createdAt).toLocaleString()}</Descriptions.Item>
      </Descriptions>

      <Typography.Title level={5}>样本</Typography.Title>
      <Table
        rowKey="id"
        dataSource={run.samples}
        pagination={{ pageSize: 20 }}
        onRow={(r) => ({ onClick: () => nav(`/run/${id}/sample/${r.id}`) })}
        columns={[
          { title: "样本", dataIndex: "externalSampleId", key: "externalSampleId" },
          { title: "状态", dataIndex: "status", key: "status" },
          { title: "Reward", key: "reward", render: (_, r) => r.reward.toFixed(3) },
          { title: "格式", key: "sFormat", render: (_, r) => r.sFormat.toFixed(3) },
          { title: "常识", key: "sCommon", render: (_, r) => r.sCommon.toFixed(3) },
          { title: "软约束", key: "sSoft", render: (_, r) => r.sSoft.toFixed(3) },
          { title: "偏好", key: "sPref", render: (_, r) => r.sPref.toFixed(3) },
        ]}
      />
    </>
  );
}
