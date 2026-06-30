/** 文件选择器（点击 + 拖拽）。受控 value: File | null。 */
import { useRef, useState } from "react"
import { cn } from "@/lib/utils"

export function FilePicker({
  value,
  onChange,
  accept,
  hint,
}: {
  value: File | null
  onChange: (f: File | null) => void
  accept?: string
  hint?: string
}) {
  const ref = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)

  return (
    <div
      onClick={() => ref.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        setDrag(true)
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDrag(false)
        const f = e.dataTransfer.files?.[0]
        if (f) onChange(f)
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed px-4 py-6 text-center transition-colors",
        drag ? "border-primary bg-primary/5" : "border-border hover:border-primary/50 hover:bg-accent/40",
      )}
    >
      <input
        ref={ref}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      {value ? (
        <div className="text-sm">
          <div className="font-medium">{value.name}</div>
          <div className="text-xs text-muted-foreground">{(value.size / 1024).toFixed(1)} KB</div>
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">
          点击或拖拽文件到此处{hint && <span className="ml-1 text-xs">（{hint}）</span>}
        </div>
      )}
    </div>
  )
}
