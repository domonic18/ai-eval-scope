import { useState } from "react"
import type { CSSProperties, ReactNode } from "react"

export interface Column<T> {
  key: string
  title: ReactNode
  num?: boolean
  render?: (row: T, index: number) => ReactNode
  style?: CSSProperties
}

/** 数据表 table.data：等宽数字列右对齐、行 hover 可点、客户端分页。 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  pageSize,
  empty,
  footer,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey?: (row: T, index: number) => string | number
  onRowClick?: (row: T) => void
  pageSize?: number
  empty?: ReactNode
  footer?: ReactNode
}) {
  const [page, setPage] = useState(1)
  const total = rows.length
  const pages = pageSize ? Math.max(1, Math.ceil(total / pageSize)) : 1
  const safePage = Math.min(page, pages)
  const start = pageSize ? (safePage - 1) * pageSize : 0
  const visible = pageSize ? rows.slice(start, start + pageSize) : rows

  return (
    <>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={c.num ? "num" : ""} style={c.style}>
                  {c.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={columns.length} style={{ textAlign: "center", cursor: "default" }}>
                  {empty ?? <span className="muted">无数据</span>}
                </td>
              </tr>
            ) : (
              visible.map((row, i) => (
                <tr
                  key={rowKey ? rowKey(row, start + i) : start + i}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  style={onRowClick ? undefined : { cursor: "default" }}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={c.num ? "num" : ""} style={c.style}>
                      {c.render
                        ? c.render(row, start + i)
                        : ((row as Record<string, ReactNode>)[c.key] ?? null)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {(footer || (pageSize && pages > 1)) && (
        <div
          className="spread"
          style={{ padding: "12px 16px", fontSize: 12, color: "var(--text-tertiary)" }}
        >
          <span>
            共 <span className="mono">{total}</span> 条
            {pageSize && pages > 1 && (
              <>
                {" · "}
                <span className="mono">
                  {safePage}/{pages}
                </span>
              </>
            )}
          </span>
          {pageSize && pages > 1 && (
            <span className="row" style={{ gap: 6 }}>
              <button
                className="btn btn-sm"
                disabled={safePage <= 1}
                onClick={() => setPage(safePage - 1)}
              >
                上一页
              </button>
              <button
                className="btn btn-sm"
                disabled={safePage >= pages}
                onClick={() => setPage(safePage + 1)}
              >
                下一页
              </button>
            </span>
          )}
          {footer}
        </div>
      )}
    </>
  )
}
