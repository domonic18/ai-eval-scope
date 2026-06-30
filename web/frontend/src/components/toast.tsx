/**
 * Toast（基于 sonner）。保留 useToast {success,error,info} API，调用点零改动。
 * main.tsx 挂 <ToastProvider/> 提供 <Toaster/>。
 */
import { toast, Toaster } from "sonner"
import type { ReactNode } from "react"

interface ToastApi {
  success: (text: string) => void
  error: (text: string) => void
  info: (text: string) => void
}

export const useToast = (): ToastApi => ({
  success: (t) => toast.success(t),
  error: (t) => toast.error(t),
  info: (t) => toast(t),
})

export function ToastProvider({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <Toaster theme="dark" richColors closeButton position="bottom-right" />
    </>
  )
}
