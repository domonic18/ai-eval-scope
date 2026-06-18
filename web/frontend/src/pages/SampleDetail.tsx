import { useEffect, useState } from "react";
import { Collapse, List, Tag, Typography, Button, Space, Card, Modal, Spin } from "antd";
import { FileOutlined, EyeOutlined } from "@ant-design/icons";
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
  return tier === "hard_gate" || tier === "hard_score" ? "red" : tier === "soft" ? "orange" : "blue";
}

/** 将 details JSON 渲染为可读的键值对列表 */
function renderDetails(details: Record<string, unknown> | null) {
  if (!details || Object.keys(details).length === 0) return null;
  const entries = Object.entries(details);
  return (
    <div style={{ marginTop: 8 }}>
      {entries.map(([key, val]) => (
        <div key={key} style={{ marginBottom: 4 }}>
          <Typography.Text strong style={{ fontSize: 12 }}>{key}: </Typography.Text>
          {Array.isArray(val) ? (
            <ul style={{ margin: "4px 0", paddingLeft: 20 }}>
              {val.map((item, i) => (
                <li key={i}>
                  <Typography.Text style={{ fontSize: 12 }}>
                    {typeof item === "object" ? JSON.stringify(item, null, 2) : String(item)}
                  </Typography.Text>
                </li>
              ))}
            </ul>
          ) : typeof val === "object" && val !== null ? (
            <pre style={{ fontSize: 11, margin: "4px 0", background: "#fafafa", padding: 8, borderRadius: 4, overflowX: "auto" }}>
              {JSON.stringify(val, null, 2)}
            </pre>
          ) : (
            <Typography.Text style={{ fontSize: 12 }}>{String(val)}</Typography.Text>
          )}
        </div>
      ))}
    </div>
  );
}

export default function SampleDetail() {
  const { id, sid } = useParams<{ id: string; sid: string }>();
  const [sample, setSample] = useState<SampleData | null>(null);
  const [previewArt, setPreviewArt] = useState<ArtifactRow | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);

  useEffect(() => {
    if (!id || !sid) return;
    api.sampleDetail(id, sid).then(setSample).catch(() => setSample(null));
  }, [id, sid]);

  async function openPreview(art: ArtifactRow) {
    setPreviewArt(art);
    setPreviewUrl(null);
    setTextContent(null);
    setLoadingContent(true);
    try {
      // 先经 JWT 鉴权获取 presigned URL（短时效），再用该 URL 加载内容（无需 auth）
      const preview = await api.artifactPreview(art.id);
      if (art.contentType.includes("html")) {
        setPreviewUrl(preview.url);
      } else {
        const resp = await fetch(preview.url);
        setTextContent(await resp.text());
      }
    } catch {
      setTextContent("（无法加载文件内容）");
    } finally {
      setLoadingContent(false);
    }
  }

  if (!sample) return <Typography.Text type="secondary">加载中…</Typography.Text>;

  const failedCount = sample.constraintResults.filter((c) => !c.passed).length;

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          样本 {sample.externalSampleId}
        </Typography.Title>
        <Tag>{sample.status}</Tag>
        <Tag color="green">Reward {sample.reward.toFixed(3)}</Tag>
        {failedCount > 0 && <Tag color="red">{failedCount} 项失败</Tag>}
      </Space>

      <Typography.Title level={5}>约束结果（{sample.constraintResults.length} 项）</Typography.Title>
      <List
        bordered
        dataSource={sample.constraintResults}
        renderItem={(c) => {
          const hasDetail =
            (c.details && Object.keys(c.details).length > 0) ||
            (c.moduleResults && Object.keys(c.moduleResults).length > 0);

          return (
            <List.Item>
              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                {/* 主行：tier / 状态 / 名称 / 分数 */}
                <Space wrap>
                  <Tag color={tierColor(c.tier)}>{c.tier}</Tag>
                  <Tag color={c.passed ? "green" : "red"}>{c.passed ? "PASS" : "FAIL"}</Tag>
                  <Typography.Text strong>{c.name}</Typography.Text>
                  <Typography.Text type="secondary">分数 {c.score.toFixed(3)}</Typography.Text>
                  {c.rawScore !== null && c.rawScore !== c.score && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      (原始 {c.rawScore.toFixed(3)})
                    </Typography.Text>
                  )}
                </Space>

                {/* 原因 */}
                <Typography.Text>{c.reason}</Typography.Text>

                {/* 元信息 */}
                <Space size="small" style={{ fontSize: 12 }}>
                  <Typography.Text type="secondary">{c.constraintId}</Typography.Text>
                  {c.ruleId && c.ruleId !== c.constraintId && (
                    <Typography.Text type="secondary">rule: {c.ruleId}</Typography.Text>
                  )}
                  <Typography.Text type="secondary">耗时 {c.durationMs.toFixed(0)}ms</Typography.Text>
                  {c.judgeProvider && (
                    <Typography.Text type="secondary">
                      judge: {c.judgeProvider}/{c.judgeModel ?? "?"}
                    </Typography.Text>
                  )}
                </Space>

                {/* 可展开详情 */}
                {hasDetail && (
                  <Collapse
                    ghost
                    size="small"
                    style={{ marginTop: 4 }}
                    items={[
                      {
                        key: "detail",
                        label: (
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            📋 评估详情
                          </Typography.Text>
                        ),
                        children: (
                          <>
                            {renderDetails(c.details)}
                            {c.moduleResults && Object.keys(c.moduleResults).length > 0 && (
                              <>
                                <Typography.Text strong style={{ fontSize: 12, display: "block", marginTop: 8 }}>
                                  模块结果
                                </Typography.Text>
                                <pre style={{ fontSize: 11, margin: "4px 0", background: "#fafafa", padding: 8, borderRadius: 4, overflowX: "auto" }}>
                                  {JSON.stringify(c.moduleResults, null, 2)}
                                </pre>
                              </>
                            )}
                          </>
                        ),
                      },
                    ]}
                  />
                )}
              </Space>
            </List.Item>
          );
        }}
      />

      {/* 源文件（kind=output，支持在线预览） */}
      {(() => {
        const sourceFiles = sample.artifacts.filter((a) => a.kind === "output");
        const otherArts = sample.artifacts.filter((a) => a.kind !== "output");
        return (
          <>
            {sourceFiles.length > 0 && (
              <>
                <Typography.Title level={5} style={{ marginTop: 24 }}>
                  源文件（{sourceFiles.length} 个，可在线预览）
                </Typography.Title>
                <Card>
                  <Space wrap>
                    {sourceFiles.map((a) => (
                      <Space key={a.id}>
                        <Button size="small" icon={<EyeOutlined />} onClick={() => openPreview(a)}>
                          {a.originalName || a.id}
                        </Button>
                      </Space>
                    ))}
                  </Space>
                </Card>
              </>
            )}

            {otherArts.length > 0 && (
              <>
                <Typography.Title level={5} style={{ marginTop: 24 }}>
                  其他制品
                </Typography.Title>
                <Card>
                  <Space wrap>
                    {otherArts.map((a) => (
                      <Button key={a.id} icon={<FileOutlined />} href={api.artifactUrl(a.id)} target="_blank">
                        {a.originalName || a.kind} ({a.kind})
                      </Button>
                    ))}
                  </Space>
                </Card>
              </>
            )}
          </>
        );
      })()}

      {/* 文件预览 Modal */}
      <Modal
        title={previewArt?.originalName || "预览"}
        open={!!previewArt}
        onCancel={() => { setPreviewArt(null); setPreviewUrl(null); setTextContent(null); }}
        footer={null}
        width="85%"
        styles={{ body: { maxHeight: "75vh", overflow: "auto" } }}
      >
        {loadingContent ? (
          <div style={{ textAlign: "center", padding: 40 }}><Spin /></div>
        ) : previewUrl ? (
          <iframe
            src={previewUrl}
            style={{ width: "100%", height: "70vh", border: "1px solid #d9d9d9", borderRadius: 4 }}
            title={previewArt?.originalName || "preview"}
          />
        ) : (
          <pre style={{ fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-all", background: "#fafafa", padding: 12, borderRadius: 4 }}>
            {textContent}
          </pre>
        )}
      </Modal>
    </>
  );
}
