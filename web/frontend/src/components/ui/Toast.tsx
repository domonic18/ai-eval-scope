import { createContext, useCallback, useContext, useState } from "react"
import { createPortal } from "react-dom"
import type { ReactNode } from "react"

type Kind = "success" | "error" | "info"
interface ToastItem {
  id: number
  kind: Kind
  text: string
}

interface ToastApi {
  success: (text: string) => void
  error: (text: string) => void
  info: (text: string) => void
}

const ToastCtx = createContext<ToastApi>({ success() {}, error() {}, info() {} })
export const useToast = () => useContext(ToastCtx)

let seq = 0

const KIND_STYLE: Record<Kind, { border: string; color: string }> = {
  success: { border: "rgba(63,185,80,0.4)", color: "var(--success)" },
  error: { border: "rgba(248,81,73,0.4)", color: "var(--danger)" },
  info: { border: "var(--accent-line)", color: "var(--accent)" },
}

/** 全局轻量 Toast（替代 AntD message）。Portal 挂在 body 右下，自动消失。 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])

  const show = useCallback((kind: Kind, text: string) => {
    const id = ++seq
    setItems((prev) => [...prev, { id, kind, text }])
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 3200)
  }, [])

  const api: ToastApi = {
    success: (t) => show("success", t),
    error: (t) => show("error", t),
    info: (t) => show("info", t),
  }

  return (
    <ToastCtx.Provider value={api}>
      {children}
      {createPortal(
        <div
          style={{
            position: "fixed",
            right: 20,
            bottom: 20,
            display: "flex",
            flexDirection: "column",
            gap: 10,
            zIndex: 1000,
          }}
        >
          {items.map((t) => {
            const s = KIND_STYLE[t.kind]
            return (
              <div
                key={t.id}
                style={{
                  minWidth: 240,
                  maxWidth: 380,
                  background: "var(--bg-elevated)",
                  border: `1px solid ${s.border}`,
                  borderLeft: `3px solid ${s.color}`,
                  borderRadius: 8,
                  boxShadow: "var(--shadow-lg)",
                  padding: "11px 14px",
                  fontSize: 13,
                  color: "var(--text-primary)",
                  animation: "es-rise .35s var(--ease)",
                }}
              >
                {t.text}
              </div>
            )
          })}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  )
}
