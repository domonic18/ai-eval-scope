/** 超管后台 · LLM 模型配置（arch/16 §6.2-四 云端形态）。
 * 多模型 CRUD + 连通性测试 + 设默认；role 为角色（text/vision/agent），
 * executor 经 /api/public/llm-config 按角色拉取（替代原导出 llm_config.yaml）。
 * provider 为协议（OpenAI / Anthropic）；api_key 加密存储，回显仅脱敏。 */
import { useEffect, useState } from "react"
import { api, type LlmModelInput, type LlmModelVO } from "../../api/client"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Label } from "@/components/shadcn/label"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import { useToast } from "../../hooks/useToast"
import { Badge } from "@/components/shadcn/badge"
import { DataTable, Page, PageHead, type Column } from "../../components/shared"
import { Pencil, Plus, Star, Trash2, Zap } from "lucide-react"

type Provider = "openai" | "anthropic"
const PROVIDER_LABEL: Record<Provider, string> = { openai: "OpenAI 协议", anthropic: "Anthropic 协议" }
type Role = "text" | "vision" | "agent"
const ROLE_LABEL: Record<Role, string> = { text: "text·评估文本", vision: "vision·视觉", agent: "agent·执行侧" }

const emptyForm: LlmModelInput = {
  name: "",
  provider: "openai",
  role: "text",
  baseUrl: "",
  apiKey: "",
  modelName: "",
  isActive: true,
  isDefault: false,
  extra: { temperature: 0, max_tokens: 8192 },
}

export default function AdminLlmModels() {
  const toast = useToast()
  const [rows, setRows] = useState<LlmModelVO[]>([])
  const [editing, setEditing] = useState<LlmModelVO | null>(null)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<LlmModelInput>(emptyForm)
  const [busy, setBusy] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [del, setDel] = useState<LlmModelVO | null>(null)

  // 加载列表：effect 仅在 mount 跑一次，避免依赖不稳定对象（toast）导致无限重渲染/轮询。
  // 写操作（test/setDefault/delete/export）成功后手动调 load() 刷新。
  const load = async () => {
    try {
      setRows(await api.adminListLlmModels())
    } catch {
      toast.error("加载 LLM 配置失败")
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openCreate() {
    setEditing(null)
    setForm(emptyForm)
    setOpen(true)
  }
  function openEdit(r: LlmModelVO) {
    setEditing(r)
    setForm({
      name: r.name,
      provider: r.provider,
      role: r.role,
      baseUrl: r.baseUrl ?? "",
      apiKey: "",
      modelName: r.modelName,
      isActive: r.isActive,
      isDefault: r.isDefault,
      extra: r.extra ?? { temperature: 0, max_tokens: 8192 },
    })
    setOpen(true)
  }

  async function submit() {
    if (!form.name || !form.modelName) {
      toast.error("名称与模型名必填")
      return
    }
    setBusy(true)
    try {
      const { apiKey, ...rest } = form
      const payload = editing ? (apiKey ? form : rest) : { ...form, apiKey: apiKey || "" }
      if (editing) await api.adminUpdateLlmModel(editing.id, payload)
      else await api.adminCreateLlmModel(payload as LlmModelInput)
      toast.success(editing ? "已更新" : "已创建")
      setOpen(false)
      await load()
    } catch (e) {
      toast.error((e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? "保存失败")
    } finally {
      setBusy(false)
    }
  }

  async function test(r: LlmModelVO) {
    setTestingId(r.id)
    try {
      const result = await api.adminTestLlmModel(r.id)
      if (result.status === "success") toast.success(`${r.name} 连通正常`)
      else toast.error(`${r.name} 测试失败：${result.detail}`)
      await load()
    } catch {
      toast.error("测试请求失败")
    } finally {
      setTestingId(null)
    }
  }

  async function setDefault(r: LlmModelVO) {
    try {
      await api.adminSetDefaultLlmModel(r.id)
      toast.success(`${r.name} 已设为默认`)
      await load()
    } catch {
      toast.error("设默认失败")
    }
  }

  async function confirmDelete() {
    if (!del) return
    try {
      await api.adminDeleteLlmModel(del.id)
      toast.success("已删除")
      setDel(null)
      await load()
    } catch {
      toast.error("删除失败")
    }
  }

  const columns: Column<LlmModelVO>[] = [
    {
      key: "name",
      title: "名称",
      render: (r) => (
        <span className="flex items-center gap-1.5">
          {r.isDefault && <Star className="size-3.5 text-warning" />}
          <span className="font-medium">{r.name}</span>
        </span>
      ),
    },
    { key: "provider", title: "协议", render: (r) => <Badge variant="outline">{PROVIDER_LABEL[r.provider as Provider] ?? r.provider}</Badge> },
    { key: "role", title: "角色", render: (r) => <Badge variant="secondary">{ROLE_LABEL[r.role as Role] ?? r.role}</Badge> },
    { key: "modelName", title: "模型", render: (r) => <span className="font-mono text-xs">{r.modelName}</span> },
    { key: "apiKeyMasked", title: "API Key", render: (r) => <span className="font-mono text-xs text-muted-foreground">{r.apiKeyMasked}</span> },
    {
      key: "status",
      title: "状态",
      render: (r) => <StatusBadge r={r} />,
    },
    {
      key: "actions",
      title: "",
      render: (r) => (
        <div className="flex items-center gap-1">
          <Button size="icon-xs" variant="ghost" title="测试" disabled={testingId === r.id} onClick={() => test(r)}>
            <Zap className="size-3.5" />
          </Button>
          <Button size="icon-xs" variant="ghost" title="设为默认" disabled={r.isDefault} onClick={() => setDefault(r)}>
            <Star className="size-3.5" />
          </Button>
          <Button size="icon-xs" variant="ghost" title="编辑" onClick={() => openEdit(r)}>
            <Pencil className="size-3.5" />
          </Button>
          <Button size="icon-xs" variant="ghost" title="删除" className="text-destructive" onClick={() => setDel(r)}>
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      ),
    },
  ]

  return (
    <Page>
      <PageHead
        title="LLM 模型配置"
        sub="管理系统所用 LLM（OpenAI / Anthropic 协议）；按角色供评估器/执行侧拉取，默认模型供配置资产 AI 生成使用"
        right={
          <div className="flex gap-2">
            <Button onClick={openCreate}>
              <Plus className="size-4" /> 新增模型
            </Button>
          </div>
        }
      />
      <DataTable rows={rows} columns={columns} rowKey={(r) => r.id} empty="暂无 LLM 模型，点击「新增模型」" />

      {/* 新增 / 编辑 */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑模型" : "新增模型"}</DialogTitle>
            <DialogDescription>配置协议、模型、API Key；API Key 加密存储，仅回显脱敏。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label>名称</Label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如 Kimi Judge" />
              </div>
              <div>
                <Label>协议</Label>
                <select
                  className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value })}
                >
                  <option value="openai">OpenAI 协议</option>
                  <option value="anthropic">Anthropic 协议</option>
                </select>
              </div>
              <div>
                <Label>角色</Label>
                <select
                  className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={form.role ?? "text"}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                >
                  <option value="text">text·评估文本</option>
                  <option value="vision">vision·视觉</option>
                  <option value="agent">agent·执行侧</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>base_url</Label>
                <Input
                  className="font-mono text-xs"
                  value={form.baseUrl ?? ""}
                  onChange={(e) => setForm({ ...form, baseUrl: e.target.value })}
                  placeholder={form.provider === "anthropic" ? "https://api.anthropic.com" : "https://api.openai.com/v1"}
                />
              </div>
              <div>
                <Label>模型名</Label>
                <Input
                  className="font-mono text-xs"
                  value={form.modelName}
                  onChange={(e) => setForm({ ...form, modelName: e.target.value })}
                  placeholder="如 moonshot-v1-128k"
                />
              </div>
            </div>
            <div>
              <Label>API Key</Label>
              <Input
                type="password"
                value={form.apiKey ?? ""}
                onChange={(e) => setForm({ ...form, apiKey: e.target.value })}
                placeholder={editing ? "••••（留空不改）" : "明文，加密存储"}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>temperature</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={String((form.extra as Record<string, unknown>)?.temperature ?? 0)}
                  onChange={(e) => setForm({ ...form, extra: { ...form.extra, temperature: parseFloat(e.target.value) || 0 } })}
                />
              </div>
              <div>
                <Label>max_tokens</Label>
                <Input
                  type="number"
                  value={String((form.extra as Record<string, unknown>)?.max_tokens ?? 8192)}
                  onChange={(e) => setForm({ ...form, extra: { ...form.extra, max_tokens: parseInt(e.target.value) || 8192 } })}
                />
              </div>
            </div>
            <div className="flex gap-4">
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={form.isDefault} onChange={(e) => setForm({ ...form, isDefault: e.target.checked })} />
                设为默认模型
              </label>
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={form.isActive} onChange={(e) => setForm({ ...form, isActive: e.target.checked })} />
                启用
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button onClick={submit} disabled={busy}>
              {busy ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <Dialog open={!!del} onOpenChange={(v) => !v && setDel(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除模型</DialogTitle>
            <DialogDescription>确认删除「{del?.name}」？{del?.isDefault ? "该模型为默认，删除后将自动改派首个启用项。" : ""}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDel(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  )
}

function StatusBadge({ r }: { r: LlmModelVO }) {
  if (!r.isActive) return <Badge variant="secondary">已停用</Badge>
  if (r.lastTestStatus === "success") return <Badge className="bg-success/15 text-success">正常</Badge>
  if (r.lastTestStatus === "failed") return <Badge className="bg-destructive/15 text-destructive">异常</Badge>
  return <Badge variant="outline">未测试</Badge>
}
