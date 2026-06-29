import { useEffect, useMemo, useState } from "react"
import { useParams } from "react-router-dom"
import { api } from "../api/client"
import type { ArtifactRow, ConstraintRow } from "../types"
import { fmt3 } from "../lib/format"
import { SCORE_EXPLAIN, STAGES, sampleBadge, tierToChip } from "../lib/eval"
import { Badge, Button, Empty, Explain, Select, useCrumbs, useToast } from "../components/ui"
import { IconCaret, IconExternal } from "../components/icons"

interface SampleData {
  id: string
  externalSampleId: string
  status: string
  reward: number
  constraintResults: ConstraintRow[]
  artifacts: ArtifactRow[]
}

type PreviewMode = "iframe" | "img" | "text" | "none"
interface PreviewState {
  mode: PreviewMode
  url?: string
  text?: string
}
type PrevTab = "doc" | "shot" | "trace"

function avg(nums: number[]): number | undefined {
  if (nums.length === 0) return undefined
  return nums.reduce((a, b) => a + b, 0) / nums.length
}

export default function SampleDetail() {
  const { id, sid } = useParams<{ id: string; sid: string }>()
  const { setCrumbs } = useCrumbs()
  const toast = useToast()
  const [sample, setSample] = useState<SampleData | null>(null)

  useEffect(() => {
    if (!id || !sid) return
    api
      .sampleDetail(id, sid)
      .then((s) => {
        setSample(s)
        setCrumbs([
          { label: "项目看板", to: "/dashboard" },
          { label: "运行", to: `/run/${id}` },
          { label: <span className="mono">{s.externalSampleId}</span> },
        ])
      })
      .catch(() => setSample(null))
  }, [id, sid, setCrumbs])

  // 阶段聚合得分（用于阶段头）—— 必须在早退 return 之前调用
  const stageScores = useMemo(() => {
    const cs = sample?.constraintResults ?? []
    const byTier = (t: string) => cs.filter((c) => c.tier === t)
    const fmt = byTier("hard_gate")
    const com = byTier("hard_score")
    const soft = byTier("soft")
    const pref = byTier("preference")
    return {
      sFormat: fmt.length ? (fmt.every((c) => c.passed) ? 1 : -3) : undefined,
      sCommon: com.length ? (com.every((c) => c.passed) ? 1 : 0) : undefined,
      sSoft: avg(soft.map((c) => c.score)),
      sPref: avg(pref.map((c) => c.score)),
    }
  }, [sample])

  if (!sample) {
    return (
      <div className="page">
        <Empty title="加载样本详情…" />
      </div>
    )
  }

  const failedCount = sample.constraintResults.filter((c) => !c.passed).length
  const sb = sampleBadge(sample.status)

  return (
    <>
      <div className="scanlines" />
      {/* 样本摘要条 */}
      <div className="sample-bar">
        <div className="row" style={{ gap: 10 }}>
          <span className="mono" style={{ fontWeight: 650, fontSize: 15 }}>
            {sample.externalSampleId}
          </span>
          <Badge variant={sb.variant}>{sb.label}</Badge>
          <Badge variant="neutral">
            综合奖励{" "}
            <b className="mono" style={{ color: "var(--danger)", marginLeft: 3 }}>
              {fmt3(sample.reward)}
            </b>
          </Badge>
          {failedCount > 0 && (
            <Badge variant="danger" dot="var(--danger)">
              {failedCount} 项约束失败
            </Badge>
          )}
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Button size="sm" onClick={() => toast.info("请在运行详情的样本表中切换样本")}>
            上一个
          </Button>
          <Button size="sm" onClick={() => toast.info("请在运行详情的样本表中切换样本")}>
            下一个
          </Button>
        </div>
      </div>

      <div className="split reveal">
        {/* 左：约束结论 */}
        <div className="pane pane-left r-1">
          {STAGES.map((stage) => {
            const constraints = sample.constraintResults.filter((c) => stage.tiers.includes(c.tier))
            if (constraints.length === 0) return null
            return (
              <div className="stage" key={stage.key}>
                <div className="stage-head">
                  <span className="stage-bar" style={{ background: stage.bar }} />
                  <h3>{stage.title}</h3>
                  {stage.chips.map((ch) => (
                    <span key={ch.label} className={`chip chip-${ch.chip}`}>
                      {ch.label}
                    </span>
                  ))}
                  <span className="stage-score">
                    {stage.scoreExplainKey && (
                      <>
                        {stage.scoreText?.(stageScores)}{" "}
                        <Explain content={SCORE_EXPLAIN[stage.scoreExplainKey]} />
                      </>
                    )}
                  </span>
                </div>
                {constraints.map((c) => (
                  <ConstraintItem key={c.id} c={c} />
                ))}
              </div>
            )
          })}
          {sample.constraintResults.length === 0 && <Empty title="无约束结果" />}
        </div>

        {/* 右：制品预览 */}
        <div className="pane pane-right r-2">
          <PreviewPane
            artifacts={sample.artifacts}
            isMultimodal={sample.constraintResults.some((c) => c.constraintId?.includes("vision"))}
          />
        </div>
      </div>
    </>
  )
}

/** 单条约束（可展开，失败默认展开高亮）。 */
function ConstraintItem({ c }: { c: ConstraintRow }) {
  const [open, setOpen] = useState(!c.passed)
  const chip = tierToChip(c.tier)
  const method = c.judgeProvider ? "LLM_JUDGE" : "RULE"
  return (
    <div className={`constraint ${!c.passed ? "fail" : ""} ${open ? "open" : ""}`}>
      <div className="c-head" onClick={() => setOpen((o) => !o)}>
        {c.passed ? <Badge variant="success">PASS</Badge> : <Badge variant="danger">FAIL</Badge>}
        <span className="c-name">
          {c.name}
          <span className="cid">{c.constraintId}</span>
        </span>
        <span className="c-score" style={{ color: c.passed ? "var(--success)" : "var(--danger)" }}>
          {c.score.toFixed(2)}
        </span>
        <IconCaret size={14} className="c-caret" />
      </div>
      <div className="c-body">
        {c.reason && <div className="c-reason">{c.reason}</div>}
        {/* 用户关心的「存在什么问题」：从 details 提取 errors 结构化展示 */}
        {constraintErrors(c.details).length > 0 && (
          <div
            style={{
              margin: "8px 0",
              padding: "8px 10px",
              background: "rgba(248,81,73,0.06)",
              border: "1px solid rgba(248,81,73,0.2)",
              borderRadius: "var(--r-sm)",
            }}
          >
            <div style={{ fontSize: 12, color: "var(--danger)", marginBottom: 4 }}>发现的问题</div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--text-secondary)" }}>
              {constraintErrors(c.details).map((e, i) => (
                <li key={i} style={{ marginBottom: 2 }}>
                  {e}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="c-meta">
          <span>
            <b>方法</b> {method}
          </span>
          {c.judgeProvider && (
            <span>
              <b>Judge</b> {c.judgeProvider}/{c.judgeModel ?? "?"}
            </span>
          )}
          <span>
            <b>耗时</b> {Math.round(c.durationMs)}ms
          </span>
          {chip !== "hard" && (
            <span>
              <b>层级</b> {c.tier}
            </span>
          )}
        </div>
        {/* 调试详情（原始 JSON，默认折叠，不占主视觉） */}
        {hasDebug(c) && (
          <details style={{ marginTop: 10 }}>
            <summary
              style={{ cursor: "pointer", color: "var(--text-tertiary)", fontSize: 12, userSelect: "none" }}
            >
              调试详情（files_checked / formulas_checked 等技术细节）
            </summary>
            <div style={{ marginTop: 6 }}>
              {c.details && Object.keys(c.details).length > 0 && <DetailsBlock details={c.details} />}
              {c.moduleResults && Object.keys(c.moduleResults).length > 0 && (
                <DetailsBlock details={c.moduleResults} />
              )}
            </div>
          </details>
        )}
      </div>
    </div>
  )
}

/** 从 details 提取 errors（具体问题描述，用户关心的「存在什么问题」）。 */
function constraintErrors(details: Record<string, unknown> | null): string[] {
  if (!details) return []
  const e = details.errors
  if (!Array.isArray(e)) return []
  return e.filter((x): x is string => typeof x === "string")
}

/** 是否有调试详情（原始 JSON，折叠展示）。 */
function hasDebug(c: ConstraintRow): boolean {
  return (
    (!!c.details && Object.keys(c.details).length > 0) ||
    (!!c.moduleResults && Object.keys(c.moduleResults).length > 0)
  )
}

function DetailsBlock({ details }: { details: Record<string, unknown> }) {
  return (
    <pre className="code-block" style={{ margin: "0 0 10px", fontSize: 11, padding: "10px 12px" }}>
      {JSON.stringify(details, null, 2)}
    </pre>
  )
}

/** 右栏制品预览（三 Tab：原始文档 / 渲染截图 / 执行 Trace）。 */
function PreviewPane({
  artifacts,
  isMultimodal,
}: {
  artifacts: ArtifactRow[]
  isMultimodal: boolean
}) {
  const [tab, setTab] = useState<PrevTab>("doc")
  const [preview, setPreview] = useState<PreviewState>({ mode: "none" })
  const [loading, setLoading] = useState(false)

  const groups = useMemo(() => {
    const isHtml = (a: ArtifactRow) => a.contentType.includes("html") || a.kind === "output"
    const isImg = (a: ArtifactRow) => a.contentType.startsWith("image") || a.kind === "screenshot"
    const isTrace = (a: ArtifactRow) =>
      a.kind === "trace" || a.contentType.includes("json") || a.kind === "judge_record"
    return {
      doc: artifacts.filter(isHtml),
      shot: artifacts.filter(isImg),
      trace: artifacts.filter(isTrace),
      // 其余文档归入 doc
    }
  }, [artifacts])

  // 当前 Tab 可选制品（doc 兜底包含非截图/非trace的文本制品）
  const docArts = useMemo(() => {
    const used = new Set([...groups.shot, ...groups.trace].map((a) => a.id))
    return artifacts.filter((a) => !used.has(a.id))
  }, [artifacts, groups])

  const listFor = (t: PrevTab): ArtifactRow[] =>
    t === "doc" ? docArts : t === "shot" ? groups.shot : groups.trace
  const [selectedId, setSelectedId] = useState<Record<PrevTab, string>>({
    doc: "",
    shot: "",
    trace: "",
  })

  const currentList = listFor(tab)
  const currentId = selectedId[tab] || currentList[0]?.id || ""
  const current = currentList.find((a) => a.id === currentId) || currentList[0]

  useEffect(() => {
    setSelectedId((s) => ({
      ...s,
      doc: docArts[0]?.id || "",
      shot: groups.shot[0]?.id || "",
      trace: groups.trace[0]?.id || "",
    }))
  }, [docArts, groups.shot, groups.trace])

  useEffect(() => {
    let cancelled = false
    if (!current) {
      setPreview({ mode: "none" })
      return
    }
    setLoading(true)
    api
      .artifactPreview(current.id)
      .then(async (p) => {
        if (cancelled) return
        if (p.contentType.includes("html")) {
          setPreview({ mode: "iframe", url: p.url })
        } else if (p.contentType.startsWith("image")) {
          setPreview({ mode: "img", url: p.url })
        } else {
          try {
            const resp = await fetch(p.url)
            setPreview({ mode: "text", text: await resp.text() })
          } catch {
            setPreview({ mode: "text", text: "（无法加载文件内容）" })
          }
        }
      })
      .catch(() => !cancelled && setPreview({ mode: "text", text: "（无法加载文件内容）" }))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [current])

  const hasAny = artifacts.length > 0

  return (
    <>
      <div className="prev-bar">
        <div className="prev-tabs">
          {(
            [
              ["doc", "原始文档"],
              ...(isMultimodal ? ([["shot", "渲染截图"]] as [PrevTab, string][]) : []),
              ["trace", "执行 Trace"],
            ] as [PrevTab, string][]
          ).map(([k, label]) => (
            <span
              key={k}
              className={`prev-tab ${tab === k ? "active" : ""}`}
              onClick={() => setTab(k)}
            >
              {label}
            </span>
          ))}
        </div>
        <div className="row" style={{ gap: 8 }}>
          {currentList.length > 0 && (
            <Select
              style={{ width: "auto" }}
              value={currentId}
              onChange={(e) => setSelectedId((s) => ({ ...s, [tab]: e.target.value }))}
            >
              {currentList.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.originalName || a.id}
                </option>
              ))}
            </Select>
          )}
          {current && (
            <a
              className="icon-btn"
              href={api.artifactUrl(current.id)}
              target="_blank"
              rel="noreferrer"
              style={{ display: "inline-flex", textDecoration: "none" }}
            >
              <IconExternal size={15} />
            </a>
          )}
        </div>
      </div>

      <div className="prev-body">
        {!hasAny ? (
          <Empty title="无制品" children={<>该样本暂无可预览的产出物。</>} />
        ) : !current ? (
          <Empty
            title={`暂无${tab === "doc" ? "原始文档" : tab === "shot" ? "渲染截图" : "执行 Trace"}制品`}
          />
        ) : loading ? (
          <Empty title="加载中…" />
        ) : preview.mode === "iframe" ? (
          <iframe
            src={preview.url}
            style={{
              width: "100%",
              height: "70vh",
              border: "1px solid var(--border)",
              borderRadius: 8,
              background: "#fff",
            }}
            title="preview"
          />
        ) : preview.mode === "img" ? (
          <div style={{ maxWidth: 680, margin: "0 auto" }}>
            <img
              src={preview.url}
              alt="screenshot"
              style={{ width: "100%", borderRadius: 8, border: "1px solid var(--border)" }}
            />
          </div>
        ) : (
          <pre
            style={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
              background: "var(--bg-inset)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: 16,
              fontSize: 12.5,
              color: "var(--text-secondary)",
            }}
          >
            {preview.text}
          </pre>
        )}
      </div>
    </>
  )
}
