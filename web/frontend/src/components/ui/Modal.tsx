import { useEffect } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties, ReactNode } from "react";

/** 模态弹层 .scrim/.modal：点击遮罩 + Esc 关闭。通过 portal 挂到 body。 */
export function Modal({
  open,
  onClose,
  title,
  desc,
  children,
  footer,
  width = 480,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  desc?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className="scrim"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" style={{ maxWidth: width } as CSSProperties}>
        {(title || desc) && (
          <div className="modal-head">
            {title && <h2>{title}</h2>}
            {desc && <p>{desc}</p>}
          </div>
        )}
        {children && <div className="modal-body">{children}</div>}
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body
  );
}
