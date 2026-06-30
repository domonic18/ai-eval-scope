"use client"

import type { ReactNode } from "react"
import { HelpCircle } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/shadcn/tooltip"
import { cn } from "@/lib/utils"
import type { ExplainContent, ExplainRow } from "@/lib/eval"

interface ExplainTooltipProps {
  /** 说明内容；与 children 二选一。 */
  content?: ExplainContent
  /** 自定义说明内容；与 content 二选一。 */
  children?: ReactNode
  /** 触发图标类名。 */
  iconClassName?: string
  /** Tooltip 内容区类名。 */
  className?: string
  /** 弹出位置。 */
  side?: "top" | "right" | "bottom" | "left"
  /** 对齐方式。 */
  align?: "start" | "center" | "end"
  /** 悬停延迟。 */
  delayDuration?: number
}

/** 可复用的「?」说明提示组件，对齐 docs/design 原型中的 explain 弹窗。
 *  内容默认展示 title + 定义/计算/标准三段式。 */
export function ExplainTooltip({
  content,
  children,
  iconClassName,
  className,
  side = "top",
  align = "center",
  delayDuration = 200,
}: ExplainTooltipProps) {
  const body = children ?? (content ? <ExplainBody rows={content.rows} title={content.title} /> : null)
  return (
    <TooltipProvider delayDuration={delayDuration}>
      <Tooltip>
        <TooltipTrigger asChild>
          <HelpCircle
            className={cn(
              "size-3.5 cursor-help text-muted-foreground transition-colors hover:text-primary",
              iconClassName,
            )}
          />
        </TooltipTrigger>
        <TooltipContent
          side={side}
          align={align}
          sideOffset={6}
          className={cn(
            "max-w-[260px] space-y-1.5 border border-border bg-card p-3 text-card-foreground shadow-lg",
            className,
          )}
        >
          {body}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

function ExplainBody({ title, rows }: { title?: ReactNode; rows: ExplainRow[] }) {
  return (
    <div className="space-y-1.5">
      {title && <div className="text-xs font-semibold">{title}</div>}
      {rows.map((r, i) => (
        <div key={i} className="text-xs leading-relaxed text-muted-foreground">
          <span className="mr-1 font-mono text-foreground">{r.dt}</span>
          {r.dd}
        </div>
      ))}
    </div>
  )
}
