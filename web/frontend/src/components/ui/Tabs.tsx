import type { ReactNode } from "react"

/** 下划线标签页 .tabs/.tab；受控。 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
}: {
  items: { key: T; label: ReactNode; count?: ReactNode }[]
  value: T
  onChange: (key: T) => void
}) {
  return (
    <div className="tabs">
      {items.map((it) => (
        <button
          key={it.key}
          className={`tab ${it.key === value ? "active" : ""}`}
          onClick={() => onChange(it.key)}
        >
          {it.label}
          {it.count != null && <span className="count">{it.count}</span>}
        </button>
      ))}
    </div>
  )
}

/** 分段控制 .segment；受控。 */
export function Segment<T extends string>({
  items,
  value,
  onChange,
}: {
  items: { key: T; label: ReactNode }[]
  value: T
  onChange: (key: T) => void
}) {
  return (
    <div className="segment">
      {items.map((it) => (
        <button
          key={it.key}
          className={it.key === value ? "active" : ""}
          onClick={() => onChange(it.key)}
        >
          {it.label}
        </button>
      ))}
    </div>
  )
}
