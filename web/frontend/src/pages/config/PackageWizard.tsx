/**
 * 场景包创建向导 — 简化版（基本信息 → 确认 → 进入编辑器）。
 *
 * 双模式入口：
 * - AI 对话：占位，提示开发中
 * - 步骤向导：填写基本信息 → 创建场景 → 自动跳转包编辑器
 */

import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useCrumbs } from "../../context/navigation"
import { Page, PageHead } from "../../components/shared"
import { Card, CardContent } from "../../components/shadcn/card"
import { Badge } from "../../components/shadcn/badge"
import { Button } from "../../components/shadcn/button"
import { Input } from "../../components/shadcn/input"
import { Label } from "../../components/shadcn/label"
import { Textarea } from "../../components/shadcn/textarea"
import { toast } from "sonner"
import { api } from "../../api/client"
import { ArrowLeft, ClipboardList, Plus, Sparkles } from "lucide-react"

type Mode = "select" | "ai" | "form"

export default function PackageWizard() {
  const { setCrumbs } = useCrumbs()
  const nav = useNavigate()
  const [mode, setMode] = useState<Mode>("select")
  const [scenarioId, setScenarioId] = useState("")
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [busy, setBusy] = useState(false)

  useState(() => setCrumbs([{ label: "配置中心", to: "/config" }, { label: "创建场景包" }]))

  const create = async () => {
    if (!scenarioId || !name) {
      toast.error("请填写场景 ID 和名称")
      return
    }
    setBusy(true)
    try {
      await api.createScenario(scenarioId, name, description)
      toast.success(`场景 ${scenarioId} 创建成功！`)
      nav(`/config/scenarios/${scenarioId}/edit`)
    } catch (e: unknown) {
      const err = (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? "创建失败"
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page>
      <PageHead title="创建场景包" sub="选择创建方式，配置评估规则、提示词、指标与聚合策略" />

      {mode === "select" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <button
            onClick={() => setMode("ai")}
            className="group flex items-center gap-4 rounded-lg border border-border bg-card p-5 text-left transition-all hover:border-primary/50 hover:shadow-md"
          >
            <Sparkles className="size-7 shrink-0 text-primary" />
            <div className="min-w-0 flex-1">
              <div className="text-base font-semibold">AI 对话创建</div>
              <p className="mt-0.5 text-sm text-muted-foreground">
                描述评估目标，AI 自动生成规则集 / 提示词 / 指标草案
              </p>
            </div>
            <Badge className="shrink-0">推荐</Badge>
          </button>
          <button
            onClick={() => setMode("form")}
            className="group flex items-center gap-4 rounded-lg border border-border bg-card p-5 text-left transition-all hover:border-primary/50 hover:shadow-md"
          >
            <ClipboardList className="size-7 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="text-base font-semibold">手动创建</div>
              <p className="mt-0.5 text-sm text-muted-foreground">
                填写基本信息，创建后在编辑器中逐步配置
              </p>
            </div>
            <Badge variant="secondary" className="shrink-0">精细</Badge>
          </button>
        </div>
      )}

      {mode === "ai" && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setMode("select")}><ArrowLeft className="mr-1 size-4" />返回选择</Button>
            <span className="text-sm font-medium">🤖 AI 对话创建</span>
          </div>
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
              <Sparkles className="size-10 text-primary/60" />
              <h3 className="text-lg font-semibold">AI 对话创建</h3>
              <p className="max-w-md text-sm text-muted-foreground">
                通过自然语言描述评估需求，AI 将自动生成规则集、提示词、指标定义和聚合策略草案。
              </p>
              <Button onClick={() => toast.info("AI 对话创建功能开发中，敬请期待！\n当前请使用「手动创建」模式。")}>
                <Sparkles className="mr-1 size-4" /> 开始对话
              </Button>
              <p className="mt-2 text-xs text-muted-foreground/60">预计在后续版本上线</p>
            </CardContent>
          </Card>
        </div>
      )}

      {mode === "form" && (
        <div className="max-w-2xl space-y-4">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setMode("select")}><ArrowLeft className="mr-1 size-4" />返回选择</Button>
            <span className="text-sm font-medium">📋 手动创建</span>
          </div>
          <Card>
            <CardContent className="space-y-4 p-6">
              <div>
                <h3 className="text-base font-semibold">基本信息</h3>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  填写场景基本信息，确认后进入场景包编辑器逐步配置规则、提示词、数据、指标。
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>场景 ID *</Label>
                  <Input
                    className="font-mono"
                    placeholder="如 travel-itinerary"
                    value={scenarioId}
                    onChange={(e) => setScenarioId(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
                  />
                  <p className="mt-1 text-[11px] text-muted-foreground">小写字母 + 数字 + 连字符，创建后不可改</p>
                </div>
                <div>
                  <Label>场景名称 *</Label>
                  <Input placeholder="如 研学行程规划评估" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="col-span-2">
                  <Label>描述</Label>
                  <Textarea
                    placeholder="简要描述评估目标，如「评估 AI 生成的研学行程文档：行程安全 + 预算约束 + 内容质量」"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2 border-t pt-4">
                <Button variant="outline" onClick={() => setMode("select")}>取消</Button>
                <Button onClick={create} disabled={busy || !scenarioId || !name}>
                  <Plus className="mr-1 size-4" /> {busy ? "创建中…" : "创建并进入编辑器"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </Page>
  )
}
