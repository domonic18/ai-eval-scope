/**
 * Toast hook（基于 sonner）。保留 useToast {success,error,info} API，调用点零改动。
 */
import { toast } from "sonner"

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
