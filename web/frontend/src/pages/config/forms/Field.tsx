/**
 * 表单字段壳：统一「标签 + 必填标识 + 选填标识 + 输入提示」呈现，供各配置表单复用。
 * 视觉层级：标签（亮色标识）→ 输入框（可见容器内的填写值）→ 提示（带 ⓘ 图标的辅助说明），
 * 三者通过颜色 + 图标 + 容器明显区分，避免「一片灰白难分辨」。
 */
import type * as React from "react"
import { Info } from "lucide-react"
import { Label } from "../../../components/shadcn/label"

export function Field({
  label,
  hint,
  required,
  optional,
  children,
}: {
  label: string
  hint?: string
  required?: boolean
  optional?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-foreground/60">
        {label}
        {required && <span className="ml-0.5 text-red-400">*</span>}
        {!required && optional && (
          <span className="ml-1 rounded bg-white/5 px-1 py-px text-[9px] font-normal uppercase tracking-wide text-foreground/50">
            选填
          </span>
        )}
      </Label>
      {children}
      {hint && (
        <p className="flex items-start gap-1 text-[11px] leading-tight text-foreground/45">
          <Info className="mt-px size-3 shrink-0" />
          <span>{hint}</span>
        </p>
      )}
    </div>
  )
}

/** 表单 / YAML 模式切换（指标定义、聚合策略编辑器复用）。 */
export function FormYamlToggle({
  mode,
  onChange,
}: {
  mode: "form" | "yaml"
  onChange: (m: "form" | "yaml") => void
}) {
  return (
    <div className="flex rounded-md border">
      <button
        type="button"
        onClick={() => onChange("form")}
        className={`rounded-l-md px-3 py-1 text-xs transition-colors ${mode === "form" ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:text-foreground"}`}
      >
        表单
      </button>
      <button
        type="button"
        onClick={() => onChange("yaml")}
        className={`rounded-r-md px-3 py-1 text-xs transition-colors ${mode === "yaml" ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:text-foreground"}`}
      >
        YAML
      </button>
    </div>
  )
}
