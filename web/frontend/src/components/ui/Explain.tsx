import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { IconHelp } from "../icons";
import type { ExplainContent } from "../../lib/eval";

/** 同时仅允许一个 Explain 打开：记录当前打开者的关闭函数。 */
let closeCurrent: (() => void) | null = null;

/**
 * 指标说明 ? 弹层。
 *
 * 关键：弹层通过 createPortal 挂到 document.body，position:fixed 直接相对视口，
 * 彻底脱离 .metric(overflow:hidden) / 任何带 transform/filter 的祖先，
 * 避免"固定定位被祖先含块劫持"导致弹层飘到远离 ? 的位置。
 * 坐标仍按 ? 按钮的 getBoundingClientRect 计算（视口相对，与 fixed 一致）。
 */
export function Explain({ content }: { content: ExplainContent }) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLSpanElement>(null);

  const position = () => {
    const btn = btnRef.current;
    const pop = popRef.current;
    if (!btn || !pop) return;
    const GAP = 8;
    const M = 12;
    const b = btn.getBoundingClientRect();
    const pw = pop.offsetWidth;
    const ph = pop.offsetHeight;
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;

    // 水平：以按钮为中心，再夹取到视口内
    let left = b.left + b.width / 2 - pw / 2;
    left = Math.max(M, Math.min(left, vw - pw - M));

    // 垂直：默认按钮正下方；放不下则翻到上方
    let top = b.bottom + GAP;
    if (top + ph > vh - M && b.top - GAP - ph > M) top = b.top - GAP - ph;
    top = Math.max(M, Math.min(top, vh - ph - M));

    pop.style.left = `${Math.round(left)}px`;
    pop.style.top = `${Math.round(top)}px`;
  };

  useLayoutEffect(() => {
    if (open) position();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const reposition = () => position();
    const onMouseDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (btnRef.current?.contains(t)) return; // 点 ? 按钮：交给 toggle
      if (popRef.current?.contains(t)) return; // 点弹层内部：不关
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    const me = () => setOpen(false);
    return () => {
      if (closeCurrent === me) closeCurrent = null;
    };
  }, []);

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen((prev) => {
      const next = !prev;
      if (next) {
        if (closeCurrent) closeCurrent();
        closeCurrent = () => setOpen(false);
      }
      return next;
    });
  };

  return (
    <>
      <span className={`explain ${open ? "open" : ""}`}>
        <button type="button" className="explain-btn" ref={btnRef} onClick={toggle} aria-label="指标说明">
          <IconHelp size={10} />
        </button>
      </span>
      {createPortal(
        <span
          ref={popRef}
          className={`explain-pop ${open ? "open" : ""}`}
          style={open ? undefined : { visibility: "hidden", pointerEvents: "none" }}
        >
          <h5>{content.title}</h5>
          <dl>
            {content.rows.map((r, i) => (
              <div key={i} style={{ display: "contents" }}>
                <dt>{r.dt}</dt>
                <dd>{r.dd}</dd>
              </div>
            ))}
          </dl>
        </span>,
        document.body
      )}
    </>
  );
}
