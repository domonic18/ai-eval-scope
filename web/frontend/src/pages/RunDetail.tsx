import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api } from "../api/client"
import { fmt3, fmtMsRaw, num } from "../lib/format"
import { METRIC_EXPLAIN, METRIC_LABEL, THRESHOLDS, metricColor, runBadge, sampleBadge } from "../lib/eval"
import type { MetricKey } from "../lib/eval"
import {
  Badge,
  Button,
  Chip,
  DataTable,
  Empty,
  FailBar,
  Gauge,
  LinkButton,
  Metric,
  Modal,
  Segment,
  useCrumbs,
  useToast,
} from "../components/ui"
import { IconDownload, IconExternal, IconTrash } from "../components/icons"

interface SampleRow {
  id: string
  externalSampleId: string
  status: string
  reward: number
  sFormat: number
  sCommon: number
  sSoft: number
  sPref: number
}
interface RunData {
  id: string
  externalRunId: string
  projectId: string
  canDelete: boolean
  mode: string
  status: string
  totalSamples: number
  dr: number
  cpr: number
  avgReward: number
  condR: number
  avgTimeMs: number
  ruleSetVersion: string | null
  langfuseTraceId: string | null
  langfuseHost: string | null
  createdAt: string
  samples: SampleRow[]
}

type StageFilter = "format" | "commonsense" | "soft" | "pref" | null

/** 判断某阶段是否"不达标"，用于失败分布与样本筛选。 */
function stageFail(s: SampleRow, stage: NonNullable<StageFilter>): boolean {
  switch (stage) {
    case "format":
      return s.sFormat < 1
    case "commonsense":
      return s.sCommon <= 0
    case "soft":
      return s.sSoft < 0.6
    case "pref":
      return s.sPref < 0.6
  }
}

/** 样本最差阶段（用作"失败约束"列代理 chip）。 */
function worstStage(s: SampleRow): { chip: "hard" | "soft" | "pref"; label: string } | null {
  if (s.sFormat < 1) return { chip: "hard", label: "format" }
  if (s.sCommon <= 0) return { chip: "hard", label: "commonsense" }
  if (s.sSoft < 0.6) return { chip: "soft", label: "soft" }
  if (s.sPref < 0.6) return { chip: "pref", label: "pref" }
  return null
}

export default function RunDetail() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const { setCrumbs } = useCrumbs()
  const [run, setRun] = useState<RunData | null>(null)
  const [stageFilter, setStageFilter] = useState<StageFilter>(null)
  const [seg, setSeg] = useState<"all" | "fail" | "skip">("all")
  const toast = useToast()
  const [deleteOpen, setDeleteOpen] = useState(false)

  useEffect(() => {
    if (!id) return
    api
      .runDetail(id)
      .then((r) => {
        setRun(r)
        setCrumbs([
          { label: "项目看板", to: "/dashboard" },
          { label: <span className="mono">#{r.externalRunId}</span> },
        ])
      })
      .catch(() => setRun(null))
  }, [id, setCrumbs])

  const failCounts = useMemo(() => {
    if (!run) return null
    const s = run.samples
    return {
      format: s.filter((x) => stageFail(x, "format")).length,
      commonsense: s.filter((x) => stageFail(x, "commonsense")).length,
      soft: s.filter((x) => stageFail(x, "soft")).length,
      pref: s.filter((x) => stageFail(x, "pref")).length,
    }
  }, [run])
  const failMax = failCounts
    ? Math.max(failCounts.format, failCounts.commonsense, failCounts.soft, failCounts.pref, 1)
    : 1

  const filteredSamples = useMemo(() => {
    if (!run) return []
    return run.samples.filter((s) => {
      if (seg === "fail" && s.status !== "fail" && s.status !== "failed") return false
      if (seg === "skip" && s.status !== "skip" && s.status !== "skipped") return false
      if (stageFilter && !stageFail(s, stageFilter)) return false
      return true
    })
  }, [run, seg, stageFilter])

  if (!run) {
    return (
      <div className="page">
        <Empty title="加载运行详情…" />
      </div>
    )
  }

  const langfuseUrl =
    run.langfuseTraceId && run.langfuseHost
      ? `${run.langfuseHost}/trace/${run.langfuseTraceId}`
      : null
  const passCount = run.samples.filter((s) => s.status === "pass" || s.status === "passed").length
  const failCount = run.samples.filter((s) => s.status === "fail" || s.status === "failed").length
  const rb = runBadge(run.status)

  const metricBadge = (key: "DR" | "CPR" | "Reward") => {
    const val = key === "DR" ? run.dr : key === "CPR" ? run.cpr : run.avgReward
    return val >= THRESHOLDS[key] ? (
      <Badge variant="success">达标</Badge>
    ) : (
      <Badge variant="warning">{key === "Reward" ? "偏低" : "未达"}</Badge>
    )
  }

  function downloadReport(kind: "md" | "json") {
    const summary = {
      run: run!.externalRunId,
      mode: run!.mode,
      samples: run!.totalSamples,
      metrics: { DR: run!.dr, CPR: run!.cpr, Reward: run!.avgReward, CondR: run!.condR },
      pass: passCount,
      fail: failCount,
    }
    let text: string
    let mime: string
    if (kind === "json") {
      text = JSON.stringify(summary, null, 2)
      mime = "application/json"
    } else {
      text = `# 运行 #${run!.externalRunId} 报告\n\n- 样本：${run!.totalSamples}（通过 ${passCount} / 失败 ${failCount}）\n- DR=${fmt3(run!.dr)}（阈值 ≥ ${THRESHOLDS.DR}）\n- CPR=${fmt3(run!.cpr)}（阈值 ≥ ${THRESHOLDS.CPR}）\n- Reward=${fmt3(run!.avgReward)}（阈值 ≥ ${THRESHOLDS.Reward}）\n- CondR=${fmt3(run!.condR)}\n`
      mime = "text/markdown"
    }
    const blob = new Blob([text], { type: mime })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `run-${run!.externalRunId}.${kind}`
    a.click()
    URL.revokeObjectURL(url)
  }

  async function doDelete() {
    if (!id) return
    try {
      await api.deleteRun(id)
      toast.success("已删除")
      setDeleteOpen(false)
      nav(`/project/${run!.projectId}`)
    } catch (e) {
      toast.error("删除失败：" + ((e as Error).message ?? ""))
    }
  }

  return (
    <div className="page reveal">
      <div className="page-head r-1">
        <div className="page-title">
          <h1>
            <span className="mono">运行 #{run.externalRunId}</span>{" "}
            <Badge variant={rb.variant} dot={rb.dot} pulse={rb.pulse} style={{ fontSize: 12 }}>
              {rb.label}
            </Badge>
          </h1>
          <div className="sub">
            {run.mode} 模式 · {num(run.totalSamples)} 个样本 ·{" "}
            {new Date(run.createdAt).toLocaleString("zh-CN")}
          </div>
        </div>
        <div className="page-actions">
          {langfuseUrl && (
            <LinkButton
              href={langfuseUrl}
              target="_blank"
              rel="noreferrer"
              icon={<IconExternal size={15} />}
            >
              在 Langfuse 查看
            </LinkButton>
          )}
          <Button icon={<IconDownload size={15} />} onClick={() => downloadReport("md")}>
            下载报告
          </Button>
          {run.canDelete && (
            <Button
              variant="danger"
              icon={<IconTrash size={15} />}
              onClick={() => setDeleteOpen(true)}
            >
              删除运行
            </Button>
          )}
        </div>
      </div>

      {/* run meta */}
      <div className="meta-grid r-2" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
        <div className="meta-cell">
          <div className="meta-lab">规则集版本</div>
          <div className="meta-val mono">{run.ruleSetVersion ?? "—"}</div>
        </div>
        <div className="meta-cell">
          <div className="meta-lab">平均耗时 / 样本</div>
          <div className="meta-val mono">{fmtMsRaw(run.avgTimeMs)}</div>
        </div>
        <div className="meta-cell">
          <div className="meta-lab">创建时间</div>
          <div className="meta-val mono">{new Date(run.createdAt).toLocaleString("zh-CN")}</div>
        </div>
      </div>

      {/* metric cards */}
      <div
        className="r-3"
        style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14, marginBottom: 16 }}
      >
        {[
          { k: "DR" as MetricKey, val: run.dr, thr: THRESHOLDS.DR },
          { k: "CPR" as MetricKey, val: run.cpr, thr: THRESHOLDS.CPR },
          { k: "Reward" as MetricKey, val: run.avgReward, thr: THRESHOLDS.Reward },
        ].map((m) => (
          <Metric
            key={m.k}
            label={METRIC_LABEL[m.k as MetricKey]}
            value={fmt3(m.val)}
            valueColor={m.thr ? metricColor(m.k as MetricKey, m.val) : undefined}
            explain={METRIC_EXPLAIN[m.k as MetricKey]}
            badge={m.thr ? metricBadge(m.k as "DR" | "CPR" | "Reward") : undefined}
            gauge={
              <Gauge
                value={m.val}
                threshold={m.thr}
                color={m.thr ? metricColor(m.k as MetricKey, m.val) : "var(--accent)"}
              />
            }
            foot={
              m.thr ? (
                <span className="muted">阈值 ≥ {m.thr}</span>
              ) : (
                <span className="muted">门禁通过样本均值</span>
              )
            }
          />
        ))}
      </div>

      <div className="run-two r-4">
        {/* 失败分布 */}
        <div className="card">
          <div className="card-head">
            <h3>失败分布</h3>
            <span className="hint">按阶段 · 点击下钻样本</span>
          </div>
          <div className="card-body" style={{ padding: "8px 20px 16px" }}>
            {failCounts &&
            failCounts.format + failCounts.commonsense + failCounts.soft + failCounts.pref === 0 ? (
              <Empty title="无失败/偏低项" />
            ) : (
              <>
                <FailBar
                  name={<Chip variant="hard">format 格式门禁</Chip>}
                  count={failCounts?.format ?? 0}
                  max={failMax}
                  color="var(--danger)"
                  onClick={() => {
                    setStageFilter(stageFilter === "format" ? null : "format")
                    document.getElementById("samples")?.scrollIntoView({ behavior: "smooth" })
                  }}
                />
                <FailBar
                  name={<Chip variant="hard">commonsense 常识</Chip>}
                  count={failCounts?.commonsense ?? 0}
                  max={failMax}
                  color="var(--danger)"
                  onClick={() => {
                    setStageFilter(stageFilter === "commonsense" ? null : "commonsense")
                    document.getElementById("samples")?.scrollIntoView({ behavior: "smooth" })
                  }}
                />
                <FailBar
                  name={<Chip variant="soft">soft 软约束偏低</Chip>}
                  count={failCounts?.soft ?? 0}
                  max={failMax}
                  color="var(--warning)"
                  onClick={() => {
                    setStageFilter(stageFilter === "soft" ? null : "soft")
                    document.getElementById("samples")?.scrollIntoView({ behavior: "smooth" })
                  }}
                />
                <FailBar
                  name={<Chip variant="pref">preference 偏好偏低</Chip>}
                  count={failCounts?.pref ?? 0}
                  max={failMax}
                  color="var(--info)"
                  onClick={() => {
                    setStageFilter(stageFilter === "pref" ? null : "pref")
                    document.getElementById("samples")?.scrollIntoView({ behavior: "smooth" })
                  }}
                />
              </>
            )}
          </div>
        </div>

        {/* 报告摘要 */}
        <div className="card">
          <div className="card-head">
            <h3>报告摘要</h3>
            <div className="row" style={{ gap: 8 }}>
              <Button size="sm" onClick={() => downloadReport("md")}>
                MD
              </Button>
              <Button size="sm" onClick={() => downloadReport("json")}>
                JSON
              </Button>
            </div>
          </div>
          <div className="card-body report">
            <h4>总体结论</h4>
            <p>
              本次运行 {num(run.totalSamples)} 个样本，
              <strong className="tag-ok">{passCount} 通过</strong> /{" "}
              <strong className="tag-bad">{failCount} 失败</strong>。交付率(DR){" "}
              {run.dr >= THRESHOLDS.DR ? "达标" : "未达"}（{fmt3(run.dr)}）、 常识通过率(CPR){" "}
              {run.cpr >= THRESHOLDS.CPR ? "达标" : "未达"}（{fmt3(run.cpr)}），综合奖励(Reward){" "}
              <strong className={run.avgReward >= THRESHOLDS.Reward ? "tag-ok" : "tag-bad"}>
                {run.avgReward >= THRESHOLDS.Reward
                  ? "达标"
                  : `偏低（${fmt3(run.avgReward)} < ${THRESHOLDS.Reward}）`}
              </strong>
              。
            </p>
            <h4>主要问题</h4>
            <ul>
              {failCounts && failCounts.format > 0 && (
                <li>{failCounts.format} 个样本未通过格式门禁（format）。</li>
              )}
              {failCounts && failCounts.commonsense > 0 && (
                <li>{failCounts.commonsense} 个样本存在常识性错误（commonsense）。</li>
              )}
              {failCounts && failCounts.soft > 0 && (
                <li>{failCounts.soft} 个样本软约束评分偏低（soft &lt; 0.6）。</li>
              )}
              {failCounts && failCounts.pref > 0 && (
                <li>{failCounts.pref} 个样本偏好评分偏低（preference &lt; 0.6）。</li>
              )}
              {(!failCounts ||
                failCounts.format + failCounts.commonsense + failCounts.soft + failCounts.pref ===
                  0) && <li>未发现明显短板。</li>}
            </ul>
            <h4>建议</h4>
            <ul>
              <li>点击左侧"失败分布"下钻查看具体样本与约束结论。</li>
              <li>结合样本详情左右分栏，对照原文核验失败原因。</li>
            </ul>
          </div>
        </div>
      </div>

      {/* 样本表 */}
      <div className="card r-5" id="samples">
        <div className="card-head">
          <h3>
            样本{" "}
            <span className="muted" style={{ fontWeight: 400 }}>
              {num(run.samples.length)}
            </span>
          </h3>
          <div className="row" style={{ gap: 8 }}>
            <Segment<"all" | "fail" | "skip">
              value={seg}
              onChange={setSeg}
              items={[
                { key: "all", label: "全部" },
                { key: "fail", label: `失败 ${failCount}` },
                { key: "skip", label: "跳过" },
              ]}
            />
            {stageFilter && (
              <Badge
                variant="accent"
                style={{ cursor: "pointer" }}
                onClick={() => setStageFilter(null)}
              >
                筛选：{stageFilter} ✕
              </Badge>
            )}
          </div>
        </div>
        <DataTable<SampleRow>
          columns={[
            {
              key: "externalSampleId",
              title: "样本 (task_id)",
              render: (s) => <span className="mono">{s.externalSampleId}</span>,
            },
            {
              key: "status",
              title: "状态",
              render: (s) => {
                const b = sampleBadge(s.status)
                return <Badge variant={b.variant}>{b.label}</Badge>
              },
            },
            {
              key: "reward",
              title: METRIC_LABEL.Reward,
              num: true,
              render: (s) => (
                <span className={s.reward < 0.5 ? "t-del" : "t-add"}>{fmt3(s.reward)}</span>
              ),
            },
            {
              key: "sFormat",
              title: "S_format",
              num: true,
              render: (s) => (
                <span className={s.sFormat < 1 ? "t-del" : ""}>{fmt3(s.sFormat)}</span>
              ),
            },
            {
              key: "sCommon",
              title: "S_common",
              num: true,
              render: (s) => (
                <span className={s.sCommon <= 0 ? "t-del" : ""}>{fmt3(s.sCommon)}</span>
              ),
            },
            { key: "sSoft", title: "S_soft", num: true, render: (s) => fmt3(s.sSoft) },
            { key: "sPref", title: "S_pref", num: true, render: (s) => fmt3(s.sPref) },
            {
              key: "fail",
              title: "失败约束",
              render: (s) => {
                const w = worstStage(s)
                return w ? (
                  <Chip variant={w.chip}>{w.label}</Chip>
                ) : (
                  <span className="muted">—</span>
                )
              },
            },
          ]}
          rows={filteredSamples}
          rowKey={(s) => s.id}
          onRowClick={(s) => nav(`/run/${id}/sample/${s.id}`)}
          pageSize={15}
          empty={<span className="muted">无匹配样本</span>}
        />
      </div>

      {/* 删除确认 */}
      <Modal
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        title="删除运行"
        desc="删除后该运行的样本、约束结论与制品将从库中永久清除，且无法恢复；走势与看板指标将随之重算。"
        footer={
          <>
            <Button onClick={() => setDeleteOpen(false)}>取消</Button>
            <Button variant="danger" onClick={doDelete}>
              确认删除
            </Button>
          </>
        }
      />
    </div>
  )
}
