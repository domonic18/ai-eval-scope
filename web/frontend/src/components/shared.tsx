/**
 * 共享展示组件（shadcn/ui 之上）—— 列表页/管理页通用：页头、统计卡、分页、DataTable。
 * 用 Tailwind；替代旧 components/ui 的 DataTable/Metric 等。
 */
import type { ReactNode } from "react"
import { Button } from "@/components/shadcn/button"
import { Checkbox } from "@/components/shadcn/checkbox"
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
  selectable = false,
  selectedKeys,
  onSelectionChange,
  getRowId,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  empty?: ReactNode
  onRowClick?: (row: T) => void
  selectable?: boolean
  selectedKeys?: Set<string>
  onSelectionChange?: (keys: Set<string>) => void
  getRowId?: (row: T) => string
}) {
  const colCount = columns.length + (selectable ? 1 : 0)
  const ids = selectable
    ? rows.map((r) => (getRowId ? getRowId(r) : String(rowKey(r))))
    : []
  const allSelected =
    !!selectedKeys && selectable && ids.length > 0 && ids.every((id) => selectedKeys.has(id))
  const someSelected = !!selectedKeys && selectable && ids.some((id) => selectedKeys.has(id))
  const headerChecked: boolean | "indeterminate" = allSelected
    ? true
    : someSelected
      ? "indeterminate"
      : false

  const toggleAll = () => {
    if (!onSelectionChange || !selectedKeys) return
    const next = new Set(selectedKeys)
    if (allSelected) ids.forEach((id) => next.delete(id))
    else ids.forEach((id) => next.add(id))
    onSelectionChange(next)
  }
  const toggleOne = (id: string) => {
    if (!onSelectionChange || !selectedKeys) return
    const next = new Set(selectedKeys)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onSelectionChange(next)
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            {selectable && (
              <TableHead className="w-10">
                <Checkbox
                  checked={headerChecked}
                  onCheckedChange={toggleAll}
                  disabled={ids.length === 0}
                  aria-label="全选"
                />
              </TableHead>
            )}
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
              <TableCell colSpan={colCount} className="h-24 text-center text-muted-foreground">
                {empty}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row, i) => {
              const id = ids[i]
              return (
                <TableRow
                  key={rowKey(row)}
                  data-state={selectable && selectedKeys?.has(id) ? "selected" : undefined}
                  className={onRowClick ? "cursor-pointer" : ""}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {selectable && (
                    <TableCell className="w-10" onClick={(e) => e.stopPropagation()}>
                      <Checkbox
                        checked={selectedKeys?.has(id) ?? false}
                        onCheckedChange={() => toggleOne(id)}
                        aria-label="选择该行"
                      />
                    </TableCell>
                  )}
                  {columns.map((c) => (
                    <TableCell key={c.key} className={c.num ? "text-right tabular-nums" : ""}>
                      {c.render ? c.render(row) : (row as Record<string, ReactNode>)[c.key]}
                    </TableCell>
                  ))}
                </TableRow>
              )
            })
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
