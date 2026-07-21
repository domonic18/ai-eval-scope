/**
 * 配置资产 AI 生成统一结果弹窗（docs/arch/15）。
 * 展示 AI 返回内容（可读 JSON / 文本），用户「采纳」回写编辑器 / 「取消」。
 */
import { ReactNode } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import { Button } from "@/components/shadcn/button"
import { Loader2 } from "lucide-react"

export function AiResultDialog({
  open,
  loading,
  title,
  description,
  children,
  onAccept,
  onCancel,
}: {
  open: boolean
  loading: boolean
  title: string
  description?: string
  children?: ReactNode
  onAccept?: () => void
  onCancel: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onCancel()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto rounded-md border bg-muted/20 p-3 text-xs">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              AI 生成中…
            </div>
          ) : (
            children
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            取消
          </Button>
          {onAccept && (
            <Button onClick={onAccept} disabled={loading}>
              采纳
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
