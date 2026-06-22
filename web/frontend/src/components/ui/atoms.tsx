import type { CSSProperties, ReactNode } from "react"
import { useState } from "react"
import { IconCopy } from "../icons"

type BadgeVariant = "success" | "warning" | "danger" | "info" | "neutral" | "accent"

/** 状态徽章 .badge；可带圆点（颜色变量）与 running 脉冲。 */
export function Badge({
  variant = "neutral",
  dot,
  pulse,
  children,
  style,
  onClick,
  title,
}: {
  variant?: BadgeVariant
  dot?: string // CSS color for the dot
  pulse?: boolean
  children?: ReactNode
  style?: CSSProperties
  onClick?: () => void
  title?: string
}) {
  return (
    <span className={`badge badge-${variant}`} style={style} onClick={onClick} title={title}>
      {dot && <span className={`dot ${pulse ? "pulse" : ""}`} style={{ background: dot }} />}
      {children}
    </span>
  )
}

type ChipVariant = "hard" | "soft" | "pref"

/** tier 语义色 chip。 */
export function Chip({
  variant,
  children,
  style,
}: {
  variant: ChipVariant
  children: ReactNode
  style?: CSSProperties
}) {
  return (
    <span className={`chip chip-${variant}`} style={style}>
      {children}
    </span>
  )
}

/** 行内代码 .code-inline。 */
export function CodeInline({ children }: { children: ReactNode }) {
  return <code className="code-inline">{children}</code>
}

/** 代码块 .code-block，含复制按钮（复制 text 内容）。children 为展示节点。 */
export function CodeBlock({
  text,
  children,
  style,
}: {
  text?: string
  children: ReactNode
  style?: CSSProperties
}) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="code-block" style={{ position: "relative", ...style }}>
      {text && (
        <button
          className="btn btn-sm copy-btn"
          style={{ position: "absolute", top: 10, right: 10 }}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text)
              setCopied(true)
              setTimeout(() => setCopied(false), 1200)
            } catch {
              /* ignore */
            }
          }}
        >
          {copied ? (
            "已复制"
          ) : (
            <>
              <IconCopy size={13} /> 复制
            </>
          )}
        </button>
      )}
      <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{children}</pre>
    </div>
  )
}

/** 提示条 .callout。 */
export function Callout({
  variant = "info",
  icon,
  children,
  style,
}: {
  variant?: "warn" | "info" | "ok"
  icon?: ReactNode
  children: ReactNode
  style?: CSSProperties
}) {
  return (
    <div className={`callout callout-${variant}`} style={style}>
      {icon}
      <div>{children}</div>
    </div>
  )
}

/** 分隔线。 */
export function Divider({ style }: { style?: CSSProperties }) {
  return <hr className="divider" style={style} />
}

/** 骨架占位（无依赖的简单 muted 块）。 */
export function Skeleton({
  width = "100%",
  height = 14,
  radius = 6,
  style,
}: {
  width?: number | string
  height?: number | string
  radius?: number | string
  style?: CSSProperties
}) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius: radius,
        background: "var(--bg-surface)",
        border: "1px solid var(--border)",
        ...style,
      }}
    />
  )
}

/** 空态 .empty。 */
export function Empty({
  icon,
  title,
  children,
}: {
  icon?: ReactNode
  title?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="empty">
      {icon}
      {title && <div style={{ fontSize: 14, marginBottom: 6 }}>{title}</div>}
      {children && <div style={{ fontSize: 12.5 }}>{children}</div>}
    </div>
  )
}

/** 入场编排容器：.reveal，子元素自带 r-1…r-6。 */
export function Reveal({
  as: Tag = "div",
  className = "",
  children,
  style,
}: {
  as?: "div" | "section"
  className?: string
  children: ReactNode
  style?: CSSProperties
}) {
  return (
    <Tag className={`reveal ${className}`.trim()} style={style}>
      {children}
    </Tag>
  )
}
