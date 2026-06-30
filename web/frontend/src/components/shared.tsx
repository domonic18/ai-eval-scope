/**
 * 共享展示组件（shadcn/ui 之上）—— 列表页/管理页通用：页头、统计卡、分页、DataTable。
 * 用 Tailwind；替代旧 components/ui 的 DataTable/Metric 等。
 */
import type { ReactNode } from "react"
import { Button } from "@/components/shadcn/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/shadcn/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/shadcn/table"

export function PageHead({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="mt-1 text-sm text-muted-foreground">{sub}</p>}
      </div>
      {right}
    </div>
  )
}

export function StatCard({ label, value, foot }: { label: string; value: string; foot?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tracking-tight tabular-nums">{value}</div>
        {foot && <p className="mt-1 text-xs text-muted-foreground">{foot}</p>}
      </CardContent>
    </Card>
  )
}

export function Pager({
  page,
  total,
  pageSize = 50,
  onPrev,
  onNext,
}: {
  page: number
  total: number
  pageSize?: number
  onPrev: () => void
  onNext: () => void
}) {
  return (
    <div className="mt-3 flex items-center justify-end gap-3 text-sm text-muted-foreground">
      <span>
        第 {page} 页 · 共 {total}
      </span>
      <Button variant="outline" size="sm" onClick={onPrev} disabled={page <= 1}>
        上一页
      </Button>
      <Button variant="outline" size="sm" onClick={onNext} disabled={total <= page * pageSize}>
        下一页
      </Button>
    </div>
  )
}

export interface Column<T> {
  key: string
  title: ReactNode
  render?: (row: T) => ReactNode
  num?: boolean
  className?: string
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  empty = "无数据",
  onRowClick,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  empty?: ReactNode
  onRowClick?: (row: T) => void
}) {
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((c) => (
              <TableHead key={c.key} className={c.num ? "text-right" : ""}>
                {c.title}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                {empty}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <TableRow
                key={rowKey(row)}
                className={onRowClick ? "cursor-pointer" : ""}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((c) => (
                  <TableCell key={c.key} className={c.num ? "text-right tabular-nums" : ""}>
                    {c.render ? c.render(row) : (row as Record<string, ReactNode>)[c.key]}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}

/** 状态徽标：按语义色映射（outline + 文本色）。 */
export function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "active" || status === "completed"
      ? "border-emerald-500/40 text-emerald-400"
      : status === "disabled" || status === "failed"
        ? "border-red-500/40 text-red-400"
        : status === "running" || status === "queued" || status === "pending"
          ? "border-sky-500/40 text-sky-400"
          : "border-border text-muted-foreground"
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}
