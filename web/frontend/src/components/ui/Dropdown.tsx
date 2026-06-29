/**
 * 通用下拉菜单（Dropdown）— 统一深色主题的下拉样式，避免各处手写 inline 不一致。
 *
 * 用法：
 *   <Dropdown open onClose align="left|right" trigger={<按钮/>}>
 *     <DropdownLabel>邮箱</DropdownLabel>
 *     <DropdownSeparator />
 *     <DropdownItem onClick={...} active?>名称</DropdownItem>
 *     <DropdownItem variant="danger">登出</DropdownItem>
 *   </Dropdown>
 *
 * 样式集中在这一处（深色主题：--bg-elevated 弹层 + --border + hover --bg-hover + active --accent-soft）。
 */

import type { ReactNode } from "react"

interface DropdownProps {
  open: boolean
  onClose: () => void
  trigger: ReactNode
  children: ReactNode
  align?: "left" | "right"
  width?: number
}

export function Dropdown({
  open,
  onClose,
  trigger,
  children,
  align = "left",
  width = 240,
}: DropdownProps) {
  return (
    <div style={{ position: "relative" }}>
      {trigger}
      {open && (
        <>
          {/* 透明遮罩：点击外部关闭 */}
          <div style={{ position: "fixed", inset: 0, zIndex: 60 }} onClick={onClose} />
          <div
            style={{
              position: "absolute",
              top: "calc(100% + 6px)",
              ...(align === "right" ? { right: 0 } : { left: 0 }),
              minWidth: width,
              background: "var(--bg-elevated)",
              border: "1px solid var(--border)",
              borderRadius: "var(--r-md)",
              boxShadow: "var(--shadow-lg)",
              padding: 6,
              zIndex: 61,
            }}
          >
            {children}
          </div>
        </>
      )}
    </div>
  )
}

interface DropdownItemProps {
  children: ReactNode
  onClick?: () => void
  active?: boolean
  variant?: "default" | "danger"
}

export function DropdownItem({
  children,
  onClick,
  active = false,
  variant = "default",
}: DropdownItemProps) {
  const color = active
    ? "var(--accent)"
    : variant === "danger"
      ? "var(--danger)"
      : "var(--text-secondary)"
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        padding: "8px 10px",
        background: active ? "var(--accent-soft)" : "transparent",
        border: "none",
        borderRadius: "var(--r-sm)",
        color,
        fontSize: 13,
        fontWeight: active ? 600 : 500,
        cursor: "pointer",
      }}
      onMouseEnter={(e) => {
        if (!active) {
          e.currentTarget.style.background = "var(--bg-hover)"
          e.currentTarget.style.color = variant === "danger" ? "var(--danger)" : "var(--text-primary)"
        }
      }}
      onMouseLeave={(e) => {
        if (!active) {
          e.currentTarget.style.background = "transparent"
          e.currentTarget.style.color = color
        }
      }}
    >
      {children}
    </button>
  )
}

export function DropdownSeparator() {
  return <div style={{ borderTop: "1px solid var(--border)", margin: "6px 4px" }} />
}

export function DropdownLabel({ children }: { children: ReactNode }) {
  return (
    <div style={{ padding: "6px 10px", fontSize: 12, color: "var(--text-tertiary)" }}>{children}</div>
  )
}
