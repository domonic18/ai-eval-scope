import { useEffect, useState } from "react";
import { List, Tag, Typography, Button, Space, Card } from "antd";
import { FileOutlined, LinkOutlined } from "@ant-design/icons";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ConstraintRow, ArtifactRow } from "../types";

interface SampleData {
  id: string;
  externalSampleId: string;
  status: string;
  reward: number;
  constraintResults: ConstraintRow[];
  artifacts: ArtifactRow[];
}

function tierColor(tier: string): string {
  return tier === "hard_gate" ? "red" : tier === "soft" ? "orange" : "blue";
}

export default function SampleDetail() {
  const { id, sid } = useParams<{ id: string; sid: string }>();
  const [sample, setSample] = useState<SampleData | null>(null);

  useEffect(() => {
    if (!id || !sid) return;
    api.sampleDetail(id, sid).then(setSample).catch(() => setSample(null));
  }, [id, sid]);

  if (!sample) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          样本 {sample.externalSampleId}
        </Typography.Title>
        <Tag>{sample.status}</Tag>
        <Tag color="green">Reward {sample.reward.toFixed(3)}</Tag>
      </Space>

      <Typography.Title level={5}>约束结果</Typography.Title>
      <List
        bordered
        dataSource={sample.constraintResults}
        renderItem={(c) => (
          <List.Item>
            <Space direction="vertical" size={0} style={{ width: "100%" }}>
              <Space>
                <Tag color={tierColor(c.tier)}>{c.tier}</Tag>
                <Tag color={c.passed ? "green" : "red"}>{c.passed ? "PASS" : "FAIL"}</Tag>
                <Typography.Text strong>{c.name}</Typography.Text>
                <Typography.Text type="secondary">分数 {c.score.toFixed(3)}</Typography.Text>
              </Space>
              <Typography.Text type="secondary">{c.reason}</Typography.Text>
              <Space size="small">
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {c.constraintId}
                </Typography.Text>
                {c.judgeProvider && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    judge: {c.judgeProvider}/{c.judgeModel ?? "?"}
                  </Typography.Text>
                )}
              </Space>
            </Space>
          </List.Item>
        )}
      />

      {sample.artifacts.length > 0 && (
        <>
          <Typography.Title level={5} style={{ marginTop: 24 }}>
            制品
          </Typography.Title>
          <Card>
            <Space wrap>
              {sample.artifacts.map((a) => (
                <Button
                  key={a.id}
                  icon={<FileOutlined />}
                  href={api.artifactUrl(a.id)}
                  target="_blank"
                >
                  {a.originalName || a.kind} ({a.kind})
                </Button>
              ))}
            </Space>
          </Card>
        </>
      )}
    </>
  );
}
