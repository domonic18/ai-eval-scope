/**
 * 调试台（/debug）—— owner 专属。
 *
 * 把待评估内容（单个 HTML/MD 或 zip 课件包）上传，配置规则集，提交给 eval-gateway，
 * 并轮询任务状态/指标。等价于 scripts/sim_courseware_* 的 UI 版（评估为项目级：结果落到所选项目，
 * 后端用该项目的 API Key 签名转发 gateway）。
 */

import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import {
  Badge,
  Button,
  Callout,
  Empty,
  Field,
  FilePicker,
  Input,
  Metric,
  Select,
  useCrumbs,
  useOrg,
  useToast,
} from "../components/ui"
import { IconExternal } from "../components/icons"
import type { DebugJobStatus } from "../types"

const RULE_SETS = ["coursework-default", "format-only"]
const POLL_INTERVAL = 3000

interface Project {
  id: string
  name: string
  slug: string
}
interface HistoryItem {
  jobId: string
  projectId: string
  projectName: string
  ruleSet: string
  filename: string
  status: string
}

export default function DebugPage() {
  const { activeOrg, memberships } = useOrg()
  const { setCrumbs } = useCrumbs()
  const toast = useToast()

  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState("")
  const [ruleSet, setRuleSet] = useState(RULE_SETS[0])
  const [taskId, setTaskId] = useState("")
  const [taskTitle, setTaskTitle] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [job, setJob] = useState<DebugJobStatus | null>(null)
  const [activeJob, setActiveJob] = useState<{ projectId: string; jobId: string } | null>(null)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const isOwner = memberships.find((m) => m.orgId === activeOrg)?.role === "owner"

  useEffect(() => {
    setCrumbs([{ label: "调试台" }])
    return () => setCrumbs([])
  }, [setCrumbs])

  // 加载当前组织下的项目（作为评估目标）
  useEffect(() => {
    if (!activeOrg) return
    api
      .dashboard(activeOrg)
      .then((ps: Project[]) => {
        setProjects(ps)
        setProjectId((cur) => cur || ps[0]?.id || "")
      })
      .catch(() => toast.error("加载项目列表失败"))
  }, [activeOrg, toast])

  // 轮询任务状态
  useEffect(() => {
    if (!activeJob) return
    let stopped = false
    const tick = async () => {
      try {
        const j = await api.getDebugJob(activeJob.projectId, activeJob.jobId)
        if (stopped) return
        setJob(j)
        setHistory((h) =>
          h.map((it) => (it.jobId === j.job_id ? { ...it, status: j.status } : it)),
        )
        if (j.status === "completed" || j.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch {
        /* 单次轮询失败静默，下个 tick 重试 */
      }
    }
    tick()
    pollRef.current = setInterval(tick, POLL_INTERVAL)
    return () => {
      stopped = true
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [activeJob])

  async function submit() {
    if (!projectId || !file) return
    setSubmitting(true)
    try {
      const res = await api.submitDebugJob(projectId, file, ruleSet, {
        taskId: taskId.trim() || undefined,
        taskTitle: taskTitle.trim() || undefined,
      })
      const proj = projects.find((p) => p.id === projectId)
      setJob({ job_id: res.job_id, status: res.status })
      setActiveJob({ projectId, jobId: res.job_id })
      setHistory((h) => [
        {
          jobId: res.job_id,
          projectId,
          projectName: proj?.name ?? projectId,
          ruleSet: ruleSet,
          filename: file.name,
          status: res.status,
        },
        ...h,
      ])
      toast.success(`已提交，job_id=${res.job_id.slice(0, 8)}…`)
    } catch (e) {
      const msg = (e as { response?: { data?: { details?: { upstreamBody?: string } }; message?: string } })
      toast.error(msg.response?.data?.details?.upstreamBody?.slice(0, 120) || "提交失败")
    } finally {
      setSubmitting(false)
    }
  }

  const m = job?.metrics?.metrics
  const finished = job?.status === "completed" || job?.status === "failed"

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>
            调试台 <Badge variant="warning">owner</Badge>
          </h1>
          <div className="sub">
            向 eval-gateway 提交评估请求，验证课件（单页 / 单元包）质量。结果落到所选项目。
          </div>
        </div>
      </div>

      {!isOwner ? (
        <Callout variant="warn">当前组织你不是 owner，无权使用调试台。</Callout>
      ) : projects.length === 0 ? (
        <Empty>当前组织下还没有项目，请先创建项目并签发 API Key。</Empty>
      ) : (
        <>
          <div className="card r-2">
            <div className="card-head">
              <h3>提交评估</h3>
            </div>
            <div className="card-body">
              <Field label="目标项目" help="评估结果（run / 制品）落到该项目，用其 API Key 签名转发 gateway。">
                <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} style={{ width: "100%" }}>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}（{p.slug}）
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="规则集" style={{ marginTop: 16 }}>
                <Select value={ruleSet} onChange={(e) => setRuleSet(e.target.value)} style={{ width: "100%" }}>
                  {RULE_SETS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field
                label="任务 ID（task_id，可选）"
                help="决定 run 内 sample_id；不填则单页恒为 contents。填了即可在结果中按该 ID 定位。"
                style={{ marginTop: 16 }}
              >
                <Input
                  value={taskId}
                  onChange={(e) => setTaskId(e.target.value)}
                  placeholder="如 lesson-3（留空 → contents）"
                  style={{ width: "100%" }}
                />
              </Field>
              <Field label="任务标题（task_title，可选）" style={{ marginTop: 16 }}>
                <Input
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                  placeholder="如 分数入门（留空 → job_id）"
                  style={{ width: "100%" }}
                />
              </Field>
              <Callout variant="info" style={{ marginTop: 16 }}>
                <strong>参数说明</strong>
                <div style={{ fontSize: 12, lineHeight: 1.7, marginTop: 6 }}>
                  <div>
                    <code>file</code>（必填）：单页 <code>.html/.md</code> 或 <code>.zip</code> 单元包
                  </div>
                  <div>
                    <code>rule_set_id</code>（可选，默认 <code>coursework-default</code>）：
                    <code>coursework-default</code> 完整含 LLM / <code>format-only</code> 仅格式
                  </div>
                  <div>
                    <code>task_id</code>（可选）：见上，决定 sample_id
                  </div>
                  <div>
                    <code>task_title</code>（可选）：任务标题
                  </div>
                  <div>
                    <code>scope</code> 自动推断：zip → 单元，单文件 → 单页（不可设）
                  </div>
                </div>
              </Callout>
              <Field
                label="评估内容"
                help="zip 课件包 = 单元评估（多文件）；单个 .html/.md = 单页评估"
                style={{ marginTop: 16 }}
              >
                <FilePicker
                  value={file}
                  onChange={setFile}
                  accept=".html,.htm,.md,.markdown,.zip"
                  hint=".html / .md / .zip"
                />
              </Field>
              <div style={{ marginTop: 16 }}>
                <Button
                  variant="primary"
                  disabled={!projectId || !file || submitting}
                  onClick={submit}
                >
                  {submitting ? "提交中…" : "提交评估"}
                </Button>
              </div>
            </div>
          </div>

          {job && (
            <div className="card r-2">
              <div className="card-head">
                <h3>任务状态</h3>
                <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
              </div>
              <div className="card-body">
                <div className="mono" style={{ fontSize: 13, marginBottom: 12 }}>
                  job_id: {job.job_id}
                </div>
                <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13, color: "var(--text-secondary)" }}>
                  <span>规则集：{job.rule_set_id ?? "—"}</span>
                  <span>范围：{job.scope ?? "—"}</span>
                  <span>提交：{fmtTime(job.created_at)}</span>
                  <span>完成：{fmtTime(job.finished_at)}</span>
                </div>

                {!finished && (
                  <Callout variant="info" style={{ marginTop: 12 }}>
                    评估进行中（含 LLM 评判，单元包约 5–7 分钟）…
                  </Callout>
                )}

                {job.status === "completed" && m && (
                  <>
                    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 16 }}>
                      <Metric label="DR 交付率" value={fmt3(m.DR)} />
                      <Metric label="CPR 约束通过率" value={fmt3(m.CPR)} />
                      <Metric label="avg_reward" value={fmt3(m.avg_reward)} />
                      <Metric label="avg_soft" value={fmt3(m.avg_soft)} />
                      <Metric label="avg_pref" value={fmt3(m.avg_pref)} />
                      <Metric label="llm_skipped" value={String(m.llm_skipped ?? "—")} />
                    </div>
                    {job.web_run_url && (
                      <a
                        className="btn btn-sm"
                        style={{ marginTop: 16, display: "inline-flex", alignItems: "center", gap: 6 }}
                        href={job.web_run_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <IconExternal size={14} /> 在 web 平台查看
                      </a>
                    )}
                  </>
                )}

                {job.status === "failed" && job.error && (
                  <Callout variant="warn" style={{ marginTop: 12 }}>
                    <strong>评估失败：</strong>
                    {job.error.message || "未知错误"}
                    {job.error.traceback && (
                      <details style={{ marginTop: 8 }}>
                        <summary>traceback</summary>
                        <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{job.error.traceback}</pre>
                      </details>
                    )}
                  </Callout>
                )}
              </div>
            </div>
          )}

          {history.length > 0 && (
            <div className="card r-2">
              <div className="card-head">
                <h3>本次会话提交历史</h3>
              </div>
              <div className="card-body">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>job_id</th>
                      <th>项目</th>
                      <th>文件</th>
                      <th>规则集</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr key={h.jobId}>
                        <td className="mono" style={{ fontSize: 12 }}>
                          {h.jobId.slice(0, 13)}…
                        </td>
                        <td>{h.projectName}</td>
                        <td>{h.filename}</td>
                        <td>{h.ruleSet}</td>
                        <td>
                          <Badge variant={statusVariant(h.status)}>{h.status}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function statusVariant(s: string): "neutral" | "success" | "warning" | "info" {
  if (s === "completed") return "success"
  if (s === "failed") return "warning"
  if (s === "running") return "info"
  return "neutral"
}
function fmt3(n?: number): string {
  return n == null ? "—" : n.toFixed(3)
}
function fmtTime(iso?: string | null): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleTimeString()
  } catch {
    return iso
  }
}
