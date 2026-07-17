/**
 * Toast Provider（基于 sonner）。main.tsx 挂 <ToastProvider/> 提供 <Toaster/>。
 */
import { Toaster } from "sonner"
import type { ReactNode } from "react"

export function ToastProvider({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <Toaster theme="dark" richColors closeButton position="bottom-right" />
    </>
  )
}
