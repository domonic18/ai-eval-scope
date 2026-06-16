import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Breadcrumb,
  Card,
  Descriptions,
  List,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import DirectoryTree from "../components/DirectoryTree";
import ModuleScoreTable from "../components/ModuleScoreTable";
import { getTaskDetail, getTaskManifest, getEvidenceUrl } from "../api/client";
import type {
  TaskDetail as TaskDetailType,
  DirectoryManifest,
  RuleResult,
} from "../types";

function isEmptyObject(obj: unknown): boolean {
  return typeof obj === "object" && obj !== null && Object.keys(obj).length === 0;
}

function formatErrorItem(error: string): { file?: string; content?: string; explanation?: string } {
  // 尝试匹配 "文件路径: 错误类型 表达式（应为 xxx）" 的格式
  const match = error.match(/^(.+?):\s*(.+?)\s*（应为\s*(.+?)）$/);
  if (match) {
    return {
      file: match[1].trim(),
      content: match[2].trim(),
      explanation: `正确结果应为 ${match[3].trim()}`,
    };
  }
  // 退化为整体作为说明
  return { explanation: error };
}

function RuleDetail({ result }: { result: RuleResult }) {
  const { details } = result;
  if (!details || isEmptyObject(details)) {
    return <Typography.Text type="secondary">无详细检查信息</Typography.Text>;
  }

  // errors 列表特殊展示：公式/算术错误的文件、内容、解释
  if (Array.isArray(details.errors) && details.errors.length > 0) {
    return (
      <Space direction="vertical" style={{ width: "100%" }}>
        <Typography.Text type="danger" strong>
          发现 {details.errors.length} 处错误：
        </Typography.Text>
        {details.errors.map((err, idx) => {
          const { file, content, explanation } = formatErrorItem(String(err));
          return (
            <Card
              key={idx}
              size="small"
              type="inner"
              title={file ? `错误文件：${file}` : `错误 ${idx + 1}`}
              style={{ background: "#fff2f0" }}
            >
              {content && (
                <Typography.Paragraph>
                  <Typography.Text strong>错误内容：</Typography.Text>
                  <Typography.Text code copyable>
                    {content}
                  </Typography.Text>
                </Typography.Paragraph>
              )}
              {explanation && (
                <Typography.Paragraph>
                  <Typography.Text strong>解释说明：</Typography.Text>
                  {explanation}
                </Typography.Paragraph>
              )}
            </Card>
          );
        })}
        {renderOtherDetails(details, ["errors"])}
      </Space>
    );
  }

  return <>{renderOtherDetails(details)}</>;
}

function renderOtherDetails(
  details: Record<string, unknown>,
  skipKeys: string[] = []
): JSX.Element {
  const items: JSX.Element[] = [];

  for (const [key, value] of Object.entries(details)) {
    if (skipKeys.includes(key)) continue;

    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      items.push(
        <div key={key}>
          <Typography.Text strong>{key}：</Typography.Text>
          <List
            size="small"
            bordered
            dataSource={value}
            renderItem={(item) => (
              <List.Item>
                {typeof item === "object" && item !== null
                  ? JSON.stringify(item)
                  : String(item)}
              </List.Item>
            )}
          />
        </div>
      );
    } else if (typeof value === "object" && value !== null) {
      items.push(
        <div key={key}>
          <Typography.Text strong>{key}：</Typography.Text>
          <pre style={{ background: "#f6f6f6", padding: 8, borderRadius: 4 }}>
            {JSON.stringify(value, null, 2)}
          </pre>
        </div>
      );
    } else {
      items.push(
        <Typography.Paragraph key={key}>
          <Typography.Text strong>{key}：</Typography.Text>
          {String(value)}
        </Typography.Paragraph>
      );
    }
  }

  return <Space direction="vertical" style={{ width: "100%" }}>{items}</Space>;
}

export default function TaskDetail() {
  const { id, taskId } = useParams<{ id: string; taskId: string }>();
  const [detail, setDetail] = useState<TaskDetailType | null>(null);
  const [manifest, setManifest] = useState<DirectoryManifest | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id || !taskId) return;
    const load = async () => {
      setLoading(true);
      try {
        const [d, m] = await Promise.all([
          getTaskDetail(id, taskId),
          getTaskManifest(id, taskId).catch(() => null),
        ]);
        setDetail(d);
        // 后端非目录模式返回 {}，这里转成 null 不展示目录结构
        setManifest(m && Object.keys(m).length > 0 ? m : null);
      } catch (err) {
        message.error("加载任务详情失败");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id, taskId]);

  if (loading) {
    return <Spin size="large" style={{ display: "block", margin: "48px auto" }} />;
  }

  if (!detail) {
    return <Typography.Text type="danger">任务不存在</Typography.Text>;
  }

  const llmResults = detail.rule_results.filter(
    (r: RuleResult) => r.judge_provider || r.judge_model
  );

  const ruleColumns = [
    { title: "约束", dataIndex: "name", key: "name" },
    {
      title: "层级",
      dataIndex: "tier",
      key: "tier",
      render: (tier: string) => <Tag>{tier}</Tag>,
    },
    {
      title: "状态",
      dataIndex: "passed",
      key: "passed",
      render: (passed: boolean) => (
        <Tag color={passed ? "success" : "error"}>{passed ? "通过" : "未通过"}</Tag>
      ),
    },
    { title: "得分", dataIndex: "score", key: "score" },
    {
      title: "耗时(ms)",
      dataIndex: "duration_ms",
      key: "duration_ms",
      render: (v: number) => v?.toFixed?.(1) ?? v,
    },
    {
      title: "说明",
      dataIndex: "reason",
      key: "reason",
      ellipsis: true,
    },
  ];

  return (
    <div>
      <Breadcrumb style={{ marginBottom: 16 }}>
        <Breadcrumb.Item>
          <Link to="/">项目看板</Link>
        </Breadcrumb.Item>
        <Breadcrumb.Item>
          <Link to={`/run/${id}`}>运行 {id}</Link>
        </Breadcrumb.Item>
        <Breadcrumb.Item>任务 {taskId}</Breadcrumb.Item>
      </Breadcrumb>

      <Typography.Title level={2}>任务详情: {taskId}</Typography.Title>

      <Card title="得分概览" style={{ marginBottom: 24 }}>
        <Descriptions bordered>
          <Descriptions.Item label="S_format">{detail.scores.s_format}</Descriptions.Item>
          <Descriptions.Item label="S_common">{detail.scores.s_common}</Descriptions.Item>
          <Descriptions.Item label="S_soft">{detail.scores.s_soft}</Descriptions.Item>
          <Descriptions.Item label="S_pref">{detail.scores.s_pref}</Descriptions.Item>
          <Descriptions.Item label="Reward">
            <strong>{detail.scores.reward}</strong>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {manifest && (
        <Card title="目录结构" style={{ marginBottom: 24 }}>
          <DirectoryTree manifest={manifest} />
        </Card>
      )}

      <Card title="约束结果" style={{ marginBottom: 24 }}>
        <Table
          dataSource={detail.rule_results}
          columns={ruleColumns}
          rowKey="constraint_id"
          pagination={{ pageSize: 20 }}
          expandable={{
            expandedRowRender: (record: RuleResult) => <RuleDetail result={record} />,
            rowExpandable: (record: RuleResult) =>
              !!record.details && Object.keys(record.details).length > 0,
          }}
        />
      </Card>

      {llmResults.length > 0 && (
        <Card title="LLM Judge 溯源" style={{ marginBottom: 24 }}>
          <List
            dataSource={llmResults}
            renderItem={(item: RuleResult) => (
              <List.Item>
                <List.Item.Meta
                  title={`${item.name} (${item.score})`}
                  description={
                    <div>
                      <p>Provider: {item.judge_provider || "—"}</p>
                      <p>Model: {item.judge_model || "—"}</p>
                      {item.judge_record_path && (
                        <p>
                          溯源记录:{" "}
                          <a
                            href={getEvidenceUrl(id!, taskId!, item.judge_record_path)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {item.judge_record_path}
                          </a>
                        </p>
                      )}
                      {item.module_results && (
                        <ModuleScoreTable moduleResults={item.module_results} />
                      )}
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      )}

      {detail.evidence_files.length > 0 && (
        <Card title="Evidence 文件">
          <List
            dataSource={detail.evidence_files}
            renderItem={(file: string) => (
              <List.Item>
                <a
                  href={getEvidenceUrl(id!, taskId!, file)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {file}
                </a>
              </List.Item>
            )}
          />
        </Card>
      )}
    </div>
  );
}
