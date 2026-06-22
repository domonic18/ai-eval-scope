import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react"

/** 表单字段容器 .field：label + 控件 + help。 */
export function Field({
  label,
  help,
  children,
  style,
}: {
  label?: ReactNode
  help?: ReactNode
  children: ReactNode
  style?: React.CSSProperties
}) {
  return (
    <div className="field" style={style}>
      {label && <label>{label}</label>}
      {children}
      {help && <div className="help">{help}</div>}
    </div>
  )
}

/** 文本输入 .input。 */
export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props
  return <input className={["input", className].filter(Boolean).join(" ")} {...rest} />
}

/** 多行输入 .input（textarea）。 */
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className, ...rest } = props
  return <textarea className={["input", className].filter(Boolean).join(" ")} {...rest} />
}

/** 下拉选择 .select（chevron 由 theme.css 背景图提供）。 */
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className, children, ...rest } = props
  return (
    <select className={["select", className].filter(Boolean).join(" ")} {...rest}>
      {children}
    </select>
  )
}

/** 带前置图标的输入框包裹。icon 放左侧 svg。 */
export function InputIconWrap({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="input-icon-wrap" style={{ position: "relative" }}>
      <span
        style={{
          position: "absolute",
          left: 12,
          top: "50%",
          transform: "translateY(-50%)",
          color: "var(--text-tertiary)",
          display: "inline-flex",
        }}
      >
        {icon}
      </span>
      {children}
    </div>
  )
}
