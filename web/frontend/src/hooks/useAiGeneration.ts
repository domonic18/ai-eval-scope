/**
 * AI 生成统一 Hook（消除 4 个表单中的重复 AI 弹窗逻辑）。
 *
 * 封装 aiOpen/aiLoading/aiResult 状态 + run/accept/cancel + AiResultDialog props。
 * 各表单只需提供 call（异步获取结果）和 onAccept（将结果写回表单）。
 */
import { useState, useCallback, type ReactNode } from "react"
import { toast } from "sonner"

/** 从 axios 错误中提取后端 error 消息（统一替代各表单中重复的 inline cast）。 */
export function extractErr(e: unknown, fb: string): string {
  return (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb
}

export function useAiGeneration<T>(opts: {
  /** 异步调用 AI 端点，返回结果 */
  call: () => Promise<T>
  /** 采纳结果时的回调（写回表单） */
  onAccept: (result: T) => void
  /** 弹窗标题（结果阶段） */
  title: string
  /** 弹窗描述（结果阶段） */
  description?: string
  /** 结果渲染函数 */
  renderResult: (result: T) => ReactNode
  /** 采纳后的 toast 文案 */
  acceptToast?: string
}) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<T | null>(null)

  const run = useCallback(async () => {
    setOpen(true)
    setLoading(true)
    setResult(null)
    try {
      const r = await opts.call()
      setResult(r)
    } catch (e) {
      toast.error(extractErr(e, "AI 生成失败"))
      setOpen(false)
    } finally {
      setLoading(false)
    }
  }, [opts])

  const accept = useCallback(() => {
    if (!result) return
    opts.onAccept(result)
    setOpen(false)
    if (opts.acceptToast) toast.success(opts.acceptToast)
  }, [result, opts])

  const cancel = useCallback(() => {
    setOpen(false)
    setResult(null)
  }, [])

  return {
    open,
    loading,
    result,
    run,
    accept,
    cancel,
    /** 直接传给 <AiResultDialog> 的 props */
    dialogProps: {
      open,
      loading,
      title: opts.title,
      description: opts.description,
      onAccept: result ? accept : undefined,
      onCancel: cancel,
      children: result ? opts.renderResult(result) : null,
    },
  }
}
