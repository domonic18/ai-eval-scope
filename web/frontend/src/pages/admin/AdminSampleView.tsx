/** 超管后台 · 场景样本视图配置（docs/arch/09 §9.7 配置链第一环）。
 * 场景级 tab 呈现配置：在固定词表内选择 / 排序 / 命名；写入 Scenario.sampleView，
 * 样本详情页按「配置 → 机械兜底」解析（web/frontend lib/artifactTabs.ts）。 */
import { useEffect, useState } from "react"
import { api, type Scenario } from "../../api/client"
import type { SampleViewConfig, SampleViewTab } from "../../types"
import { TAB_LABELS } from "@/lib/artifactTabs"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Label } from "@/components/shadcn/label"
import { Badge } from "@/components/shadcn/badge"
import { useToast } from "../../hooks/useToast"
import { Page, PageHead, SectionCard, SectionCardContent, SectionCardHeader, SectionCardTitle } from "../../components/shared"
import { ArrowDown, ArrowUp, LayoutList } from "lucide-react"

/** 词表说明（与后端 SAMPLE_VIEW_TABS 同源；label 为样本页缺省显示名）。 */
const TAB_INFO: Record<SampleViewTab, { desc: string }> = {
  doc: { desc: "回答 / 原始文档类制品（answer.md 等）" },
  task: { desc: "原始问题（task.json，仅 Agent 会话形态）" },
  transcript: { desc: "对话过程（transcript.md，Agent 执行上传）" },
  shot: { desc: "渲染截图（多模态视觉评估）" },
  trace: { desc: "执行 Trace / 评估记录（trace.json、judge_record）" },
}
const VOCAB: SampleViewTab[] = ["doc", "task", "transcript", "shot", "trace"]

export default function AdminSampleView() {
  const toast = useToast()
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [scenarioId, setScenarioId] = useState<string>("")
  const [loaded, setLoaded] = useState<SampleViewConfig | null>(null)
  const [tabs, setTabs] = useState<SampleViewTab[]>([])
  const [docLabel, setDocLabel] = useState("")
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.scenarios()
      .then((rows) => setScenarios(rows))
      .catch(() => toast.error("加载场景清单失败"))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function selectScenario(id: string) {
    setScenarioId(id)
    if (!id) return
    setLoading(true)
    try {
      const r = await api.adminGetSampleView(id)
      setLoaded(r.sampleView)
      setTabs(r.sampleView?.tabs ?? [])
      setDocLabel(r.sampleView?.labels?.doc ?? "")
    } catch {
      toast.error("加载样本视图配置失败")
    } finally {
      setLoading(false)
    }
  }

  function toggleTab(t: SampleViewTab) {
    setTabs((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  function move(t: SampleViewTab, dir: -1 | 1) {
    setTabs((prev) => {
      const i = prev.indexOf(t)
      const j = i + dir
      if (i < 0 || j < 0 || j >= prev.length) return prev
      const next = [...prev]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }

  async function save() {
    if (!scenarioId) return
    if (tabs.length === 0) {
      toast.error("至少启用一个 tab")
      return
    }
    setBusy(true)
    try {
      const doc = docLabel.trim()
      const config: SampleViewConfig = { tabs, labels: doc ? { doc } : undefined }
      const r = await api.adminSetSampleView(scenarioId, config)
      setLoaded(r.sampleView)
      toast.success("已保存，样本详情页即时生效")
    } catch (e) {
      toast.error(((e as { response?: { data?: { error?: string } } })?.response?.data?.error as string) ?? "保存失败")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page>
      <PageHead
        title="场景样本视图"
        sub="配置各场景样本详情页的 tab 呈现（选择 / 排序 / 命名）；未配置的场景由制品证据机械推导兜底"
        right={<LayoutList className="size-5 text-muted-foreground" />}
      />

      <SectionCard>
        <SectionCardHeader>
          <SectionCardTitle>选择场景</SectionCardTitle>
        </SectionCardHeader>
        <SectionCardContent>
          <select
            className="w-full max-w-md rounded-md border bg-background px-3 py-2 text-sm"
            value={scenarioId}
            onChange={(e) => void selectScenario(e.target.value)}
          >
            <option value="">— 选择场景 —</option>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id}（{s.name}）
              </option>
            ))}
          </select>
          {scenarios.length === 0 && <p className="mt-2 text-xs text-muted-foreground">暂无场景</p>}
        </SectionCardContent>
      </SectionCard>

      {scenarioId && (
        <SectionCard>
          <SectionCardHeader>
            <SectionCardTitle>
              <span className="flex items-center gap-2">
                tab 配置
                {loaded ? (
                  <Badge className="bg-primary/15 text-primary">已配置</Badge>
                ) : (
                  <Badge variant="outline">{loading ? "读取中…" : "未配置 · 机械兜底"}</Badge>
                )}
              </span>
            </SectionCardTitle>
          </SectionCardHeader>
          <SectionCardContent className="space-y-4">
            {/* 启用顺序预览 */}
            <div className="text-xs text-muted-foreground">
              {tabs.length > 0 ? (
                <span className="flex flex-wrap items-center gap-1.5">
                  <span>显示顺序：</span>
                  {tabs.map((t, i) => (
                    <span key={t} className="flex items-center gap-1.5">
                      {i > 0 && <span className="text-border">→</span>}
                      <span className="rounded border border-border bg-card px-1.5 py-0.5 font-mono">
                        {i + 1} {TAB_LABELS[t]}
                      </span>
                    </span>
                  ))}
                </span>
              ) : (
                <span>未启用任何 tab（保存前请至少启用一个）</span>
              )}
            </div>

            {/* 词表行：勾选启用 + 排序 */}
            <div className="divide-y rounded-md border">
              {VOCAB.map((t) => {
                const on = tabs.includes(t)
                return (
                  <div key={t} className="flex items-center gap-3 px-3 py-2.5">
                    <label className="flex w-56 shrink-0 items-center gap-2 text-sm">
                      <input type="checkbox" checked={on} onChange={() => toggleTab(t)} />
                      <span className="font-mono text-xs">{t}</span>
                      <span className="font-medium">{TAB_LABELS[t]}</span>
                    </label>
                    <span className="flex-1 text-xs text-muted-foreground">{TAB_INFO[t].desc}</span>
                    {on && (
                      <span className="flex items-center gap-0.5">
                        <Button
                          size="icon-xs"
                          variant="ghost"
                          title="上移"
                          disabled={tabs.indexOf(t) === 0}
                          onClick={() => move(t, -1)}
                        >
                          <ArrowUp className="size-3.5" />
                        </Button>
                        <Button
                          size="icon-xs"
                          variant="ghost"
                          title="下移"
                          disabled={tabs.indexOf(t) === tabs.length - 1}
                          onClick={() => move(t, 1)}
                        >
                          <ArrowDown className="size-3.5" />
                        </Button>
                      </span>
                    )}
                  </div>
                )
              })}
            </div>

            {/* doc 命名覆盖 */}
            <div className="max-w-md">
              <Label>doc tab 显示名（可选）</Label>
              <Input
                value={docLabel}
                onChange={(e) => setDocLabel(e.target.value)}
                placeholder="默认随形态：Agent 会话 →「Agent 回答」，否则「原始文档」"
              />
            </div>

            <div className="flex items-center gap-2">
              <Button onClick={save} disabled={busy || tabs.length === 0}>
                {busy ? "保存中…" : "保存配置"}
              </Button>
              <span className="text-xs text-muted-foreground">
                配置外桶的制品自动并入「执行 Trace」（未启用则「原始文档」），不会隐藏
              </span>
            </div>
          </SectionCardContent>
        </SectionCard>
      )}
    </Page>
  )
}
