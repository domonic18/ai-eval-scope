/**
 * 单条规则卡片 — 引导式 + 条件化填写。
 * 检查内容 → 所属阶段（可新建）→ 评估方式（LLM/视觉/规则集/格式检查）→ 按方式绑定提示词/数据集或配置格式校验。
 * 评估方式为 4 个场景无关的通用选项（替代原课件专用硬编码评估器列表）。
 */
import { useState } from "react"
import { Button } from "../../../components/shadcn/button"
import { Input } from "../../../components/shadcn/input"
import { Label } from "../../../components/shadcn/label"
import { ChevronRight, Plus, Trash2, X } from "lucide-react"
import type { CatalogEntry, DatasetCatalogEntry } from "../../../api/client"
import type { EvalMethod, FormatCheckType, RuleItem } from "./RuleSetForm"

export interface CascadeStage {
  stage: string
  name: string
  stop_on_fail: boolean
}

// 场景无关的通用评估方式（非课件专用）
const EVAL_METHODS: { value: EvalMethod; label: string; icon: string; hint: string }[] = [
  { value: "llm", label: "LLM 评估", icon: "🤖", hint: "文本 LLM Judge，需绑定提示词" },
  { value: "llm_vision", label: "LLM 视觉评估", icon: "📸", hint: "截图 + 视觉 LLM 判断，需绑定提示词" },
  { value: "rule_set", label: "规则集评估", icon: "🔧", hint: "基于参考数据集的规则/事实校验，需绑定数据集" },
  { value: "format", label: "格式/程序化检查", icon: "📐", hint: "程序化校验（文件后缀/JSON/HTML/Markdown），不调用 LLM" },
]

// 格式检查类型预设（程序化、非 LLM、非 rule-base）
const FORMAT_CHECKS: { value: FormatCheckType; label: string; hint: string }[] = [
  { value: "extension", label: "文件后缀名", hint: "校验文件后缀是否在允许列表（后缀可配置）" },
  { value: "json_validity", label: "JSON 格式有效性", hint: "校验输出是否为合法 JSON" },
  { value: "html_validity", label: "HTML 格式有效性", hint: "校验输出是否为结构合法的 HTML" },
  { value: "markdown", label: "Markdown 格式有效性", hint: "校验输出是否为合法 Markdown" },
]

const methodOf = (m?: EvalMethod) => EVAL_METHODS.find((x) => x.value === m)

/** 方式徽标配色（soft 底 + 对应文字色，对齐原型 method-badge） */
const badgeClassOf = (m?: EvalMethod): string => {
  if (m === "llm") return "bg-primary/15 text-primary"
  if (m === "llm_vision") return "bg-cyan-500/15 text-cyan-300"
  return "border border-border bg-secondary text-muted-foreground" // rule_set / format
}

const NEW_STAGE = "__new_stage__"

/** evaluator 是否处于"派生态"（空或 llm./vision./rule./format. 前缀）；非派生视为用户自定义覆盖，不自动改写。 */
function isDerivedEvaluator(evaluator: string | undefined): boolean {
  return evaluator === undefined || evaluator === "" || /^(llm|vision|rule|format)\./.test(evaluator)
}
function deriveEvaluator(rule: RuleItem): string {
  if (rule.method === "llm") return rule.promptId ? `llm.${rule.promptId}` : ""
  if (rule.method === "llm_vision") return rule.promptId ? `vision.${rule.promptId}` : ""
  if (rule.method === "rule_set") return rule.datasetId ? `rule.${rule.datasetId}` : ""
  if (rule.method === "format") return rule.formatType ? `format.${rule.formatType}` : ""
  return rule.evaluator ?? ""
}

export function RuleCard({
  rule,
  cascade,
  prompts,
  datasets,
  onUpdate,
  onDelete,
  onNewStage,
  onNewPrompt,
  onNewDataset,
  onJumpAsset,
}: {
  rule: RuleItem
  cascade: CascadeStage[]
  prompts: CatalogEntry[]
  datasets: DatasetCatalogEntry[]
  onUpdate: (patch: Partial<RuleItem>) => void
  onDelete: () => void
  onNewStage: () => void
  onNewPrompt?: () => void
  onNewDataset?: () => void
  onJumpAsset?: (type: "prompt" | "dataset", assetId: string) => void
}) {
  const m = methodOf(rule.method)
  const needsPrompt = rule.method === "llm" || rule.method === "llm_vision"
  const needsDataset = rule.method === "rule_set"
  const needsFormat = rule.method === "format"
  const [extInput, setExtInput] = useState("")
  const [advOpen, setAdvOpen] = useState(false)

  /**
   * 切换方式或绑定资产后：若 evaluator 当前为派生态，则同步派生；
   * 若用户已手填自定义 evaluator（非派生态），则保留其覆盖值。
   */
  const reseedEvaluator = (patch: Partial<RuleItem>) => {
    if (isDerivedEvaluator(rule.evaluator)) {
      patch.evaluator = deriveEvaluator({ ...rule, ...patch })
    }
    onUpdate(patch)
  }

  return (
    <div className="rounded-md border border-border bg-secondary p-3">
      {/* 第一行：检查内容 + 方式徽标 + 删除 */}
      <div className="grid grid-cols-[1fr_auto_auto] items-end gap-2">
        <div>
          <Label className="text-[11px] text-muted-foreground/70">
            检查内容<span className="ml-0.5 text-destructive">*</span>
          </Label>
          <Input
            placeholder="如：行程安全检查 / 格式是否有效 / 教学逻辑"
            value={rule.name}
            onChange={(e) => onUpdate({ name: e.target.value })}
          />
        </div>
        {m && (
          <span
            className={`mb-1 inline-flex shrink-0 items-center gap-1 rounded-sm px-2 py-0.5 text-[11px] font-semibold ${badgeClassOf(rule.method)}`}
            title={m.hint}
          >
            {m.icon} {m.label}
          </span>
        )}
        <Button size="sm" variant="ghost" className="text-red-400" onClick={onDelete}>
          <Trash2 className="size-3.5" />
        </Button>
      </div>

      {/* 第二行：所属阶段 + 评估方式 */}
      <div className="mt-2 grid grid-cols-2 gap-2">
        <div>
          <Label className="text-[11px] text-muted-foreground/70">
            所属阶段<span className="ml-0.5 text-destructive">*</span>
          </Label>
          <select
            className="w-full rounded-md border border-border bg-secondary px-2 py-2 text-xs text-foreground"
            value={rule.stage}
            onChange={(e) => {
              if (e.target.value === NEW_STAGE) {
                onNewStage()
                return
              }
              onUpdate({ stage: e.target.value })
            }}
          >
            <option value="">选择阶段…</option>
            {cascade.map((c) => (
              <option key={c.stage} value={c.stage}>
                {c.name || c.stage}
                {c.stop_on_fail ? "（门控）" : ""}
              </option>
            ))}
            <option value={NEW_STAGE}>＋ 新建阶段…</option>
          </select>
        </div>
        <div>
          <Label className="text-[11px] text-muted-foreground/70">
            评估方式<span className="ml-0.5 text-destructive">*</span>
          </Label>
          <select
            className="w-full rounded-md border border-border bg-secondary px-2 py-2 text-xs text-foreground"
            value={rule.method ?? ""}
            onChange={(e) => {
              const method = (e.target.value || undefined) as EvalMethod | undefined
              const patch: Partial<RuleItem> = { method }
              // 切换方式时清掉无关绑定，避免脏数据
              if (method !== "llm" && method !== "llm_vision") patch.promptId = undefined
              if (method !== "rule_set") patch.datasetId = undefined
              if (method !== "format") {
                patch.formatType = undefined
                patch.extensions = undefined
              }
              reseedEvaluator(patch)
            }}
          >
            <option value="">选择评估方式…</option>
            {EVAL_METHODS.map((x) => (
              <option key={x.value} value={x.value}>
                {x.icon} {x.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 第三行：按评估方式条件化绑定资产 */}
      {needsPrompt && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <div className="min-w-[220px] flex-1">
            <Label className="text-[11px] text-muted-foreground/70">
              提示词<span className="ml-0.5 text-destructive">*</span>
            </Label>
            <select
              className="w-full rounded-md border border-border bg-secondary px-2 py-2 text-xs text-foreground"
              value={rule.promptId ?? ""}
              onChange={(e) => reseedEvaluator({ promptId: e.target.value || undefined })}
            >
              <option value="">选择提示词…</option>
              {prompts.map((p) => (
                <option key={p.asset_id} value={p.asset_id}>
                  {p.name ? `${p.asset_id} · ${p.name}` : p.asset_id}
                </option>
              ))}
            </select>
          </div>
          {rule.promptId && onJumpAsset && (
            <button
              type="button"
              onClick={() => onJumpAsset("prompt", rule.promptId!)}
              className="mb-1 text-[11px] text-primary hover:underline"
            >
              跳转编辑→
            </button>
          )}
          {onNewPrompt && (
            <Button size="sm" variant="outline" className="mb-0.5" onClick={onNewPrompt}>
              <Plus className="mr-1 size-3" />新建
            </Button>
          )}
          <p className="basis-full text-[11px] text-muted-foreground">
            {prompts.length === 0
              ? onNewPrompt
                ? "包内暂无提示词，点「新建」创建后回到此处选择。"
                : "包内暂无提示词，请先在配置中心创建。"
              : "提示词内容在左侧「提示词」资产中编辑。"}
          </p>
        </div>
      )}
      {needsDataset && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <div className="min-w-[220px] flex-1">
            <Label className="text-[11px] text-muted-foreground/70">
              数据集（参考知识）<span className="ml-0.5 text-destructive">*</span>
            </Label>
            <select
              className="w-full rounded-md border border-border bg-secondary px-2 py-2 text-xs text-foreground"
              value={rule.datasetId ?? ""}
              onChange={(e) => reseedEvaluator({ datasetId: e.target.value || undefined })}
            >
              <option value="">选择数据集…</option>
              {datasets.map((d) => (
                <option key={d.asset_id} value={d.asset_id}>
                  {d.name ? `${d.asset_id} · ${d.name}` : d.asset_id}
                </option>
              ))}
            </select>
          </div>
          {rule.datasetId && onJumpAsset && (
            <button
              type="button"
              onClick={() => onJumpAsset("dataset", rule.datasetId!)}
              className="mb-1 text-[11px] text-primary hover:underline"
            >
              编辑数据集→
            </button>
          )}
          {onNewDataset && (
            <Button size="sm" variant="outline" className="mb-0.5" onClick={onNewDataset}>
              <Plus className="mr-1 size-3" />新建
            </Button>
          )}
          <p className="basis-full text-[11px] text-muted-foreground">
            仅列出参考数据集（role=reference），用于事实/规则校验
            {datasets.length === 0 && !onNewDataset ? "；请先在配置中心创建。" : "。"}
          </p>
        </div>
      )}

      {/* 格式/程序化检查：选检查类型，后缀可增删 */}
      {needsFormat && (
        <div className="mt-2 space-y-2">
          <div>
            <Label className="text-[11px] text-muted-foreground/70">
              格式检查类型<span className="ml-0.5 text-destructive">*</span>
            </Label>
            <select
              className="w-full rounded-md border border-border bg-secondary px-2 py-2 text-xs text-foreground"
              value={rule.formatType ?? ""}
              onChange={(e) => {
                const formatType = (e.target.value || undefined) as FormatCheckType | undefined
                // 切到非后缀类型时清空后缀列表
                const patch: Partial<RuleItem> =
                  formatType === "extension" ? { formatType } : { formatType, extensions: undefined }
                reseedEvaluator(patch)
              }}
            >
              <option value="">选择检查类型…</option>
              {FORMAT_CHECKS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {rule.formatType
                ? FORMAT_CHECKS.find((f) => f.value === rule.formatType)?.hint
                : "程序化校验，不调用 LLM，常用于格式门控阶段。"}
            </p>
          </div>

          {/* 后缀名可配置列表 */}
          {rule.formatType === "extension" && (
            <div>
              <Label className="text-[11px] text-muted-foreground/70">允许的文件后缀</Label>
              <div className="flex gap-2">
                <Input
                  className="font-mono text-xs"
                  placeholder="如 md（不含点），回车或点添加"
                  value={extInput}
                  onChange={(e) => setExtInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && extInput.trim()) {
                      e.preventDefault()
                      const v = extInput.trim().replace(/^\./, "").toLowerCase()
                      const cur = rule.extensions ?? []
                      if (v && !cur.includes(v)) onUpdate({ extensions: [...cur, v] })
                      setExtInput("")
                    }
                  }}
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    if (!extInput.trim()) return
                    const v = extInput.trim().replace(/^\./, "").toLowerCase()
                    const cur = rule.extensions ?? []
                    if (v && !cur.includes(v)) onUpdate({ extensions: [...cur, v] })
                    setExtInput("")
                  }}
                >
                  <Plus className="mr-1 size-3" />添加
                </Button>
              </div>
              {(rule.extensions ?? []).length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {(rule.extensions ?? []).map((ext, ei) => (
                    <span
                      key={ei}
                      className="inline-flex items-center rounded-full border border-border bg-secondary py-0.5 pl-2 pr-1 font-mono text-[11px] text-muted-foreground"
                    >
                      .{ext}
                      <button
                        className="ml-1 text-muted-foreground hover:text-destructive"
                        title="移除"
                        onClick={() =>
                          onUpdate({ extensions: (rule.extensions ?? []).filter((_, j) => j !== ei) })
                        }
                      >
                        <X className="size-2.5" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 高级：自定义 evaluator ID（受控折叠，对齐原型 collapse-toggle） */}
      <div className="mt-2">
        <button
          type="button"
          onClick={() => setAdvOpen((o) => !o)}
          className="inline-flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronRight className={`size-3 transition-transform ${advOpen ? "rotate-90" : ""}`} />
          高级 ▸ 自定义 evaluator ID
        </button>
        {advOpen && (
          <Input
            className="mt-1.5 font-mono text-xs"
            placeholder="默认按方式+资产派生；手动填写则作为覆盖，如 my.checker"
            value={rule.evaluator ?? ""}
            onChange={(e) => onUpdate({ evaluator: e.target.value })}
          />
        )}
      </div>
    </div>
  )
}
