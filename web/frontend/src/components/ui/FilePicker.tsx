/**
 * FilePicker — 受控单文件选择（点击 + 拖拽）。
 * 用于调试台上传评估内容（单个 HTML/MD 或 zip 课件包）。
 */

import { useRef, useState, type DragEvent } from "react"
import type { ReactNode } from "react"

export function FilePicker({
  value,
  onChange,
  accept,
  hint,
}: {
  value: File | null
  onChange: (f: File | null) => void
  accept?: string
  hint?: ReactNode
}) {
  const ref = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setDrag(false)
    const f = e.dataTransfer.files?.[0]
    if (f) onChange(f)
  }

  return (
    <div className="field">
      <div
        className={`file-drop ${drag ? "drag" : ""} ${value ? "has-file" : ""}`}
        onClick={() => ref.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <input
          ref={ref}
          type="file"
          accept={accept}
          style={{ display: "none" }}
          onChange={(e) => onChange(e.target.files?.[0] ?? null)}
        />
        {value ? (
          <div className="file-meta">
            <strong>{value.name}</strong>
            <span className="file-size"> · {formatSize(value.size)}</span>
          </div>
        ) : (
          <div className="file-placeholder">点击选择或拖入文件{hint ? `（${hint}）` : ""}</div>
        )}
      </div>
      {value && (
        <button
          type="button"
          className="btn btn-sm"
          style={{ marginTop: 8 }}
          onClick={(e) => {
            e.stopPropagation()
            onChange(null)
            if (ref.current) ref.current.value = ""
          }}
        >
          清除
        </button>
      )}
      <style>{`
        .file-drop {
          border: 1px dashed var(--border, #d0d5dd);
          border-radius: 8px;
          padding: 18px 16px;
          cursor: pointer;
          text-align: center;
          color: var(--text-secondary, #667085);
          transition: border-color .15s, background .15s;
        }
        .file-drop.drag { border-color: var(--primary, #2563eb); background: rgba(37,99,235,.06); }
        .file-drop.has-file { border-style: solid; color: var(--text-primary, #101828); }
        .file-meta .file-size { color: var(--text-tertiary, #98a2b3); }
      `}</style>
    </div>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
