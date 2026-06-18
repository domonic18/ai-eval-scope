import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "default" | "primary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

interface CommonProps {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  children?: ReactNode;
  className?: string;
}

const cls = (variant: Variant, size: Size, extra?: string) =>
  ["btn", variant !== "default" && `btn-${variant}`, size !== "md" && `btn-${size}`, extra]
    .filter(Boolean)
    .join(" ");

/** 按钮组件，渲染原型 .btn；提供 href 时渲染为 <a>。 */
export function Button({
  variant = "default",
  size = "md",
  icon,
  children,
  className,
  ...rest
}: CommonProps & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button className={cls(variant, size, className)} {...rest}>
      {icon}
      {children}
    </button>
  );
}

/** 链接型按钮（.btn 样式的 <a>）。 */
export function LinkButton({
  variant = "default",
  size = "md",
  icon,
  children,
  className,
  ...rest
}: CommonProps & AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a className={cls(variant, size, className)} {...rest}>
      {icon}
      {children}
    </a>
  );
}
