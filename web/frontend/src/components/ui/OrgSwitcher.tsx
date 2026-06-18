import { useEffect, useRef, useState } from "react";
import type { Membership } from "../../types";
import { IconChevronDown } from "../icons";

/** 组织切换器 .org-switcher；点击展开下拉切换当前组织。 */
export function OrgSwitcher({
  memberships,
  activeOrg,
  onChange,
}: {
  memberships: Membership[];
  activeOrg: string | null;
  onChange: (orgId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = memberships.find((m) => m.orgId === activeOrg) ?? memberships[0];

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  if (!active) return null;

  return (
    <div className="org-switcher" ref={ref} onClick={() => setOpen((o) => !o)} style={{ position: "relative" }}>
      <div className="org-avatar">{active.org.name?.[0] ?? "?"}</div>
      <div className="org-meta">
        <div className="org-name">{active.org.name}</div>
        <div className="org-plan">{active.org.slug}</div>
      </div>
      <IconChevronDown size={14} style={{ color: "var(--text-tertiary)" }} />

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            right: 0,
            background: "var(--bg-elevated)",
            border: "1px solid var(--border-hover)",
            borderRadius: 8,
            boxShadow: "var(--shadow-lg)",
            padding: 6,
            zIndex: 50,
          }}
        >
          {memberships.map((m) => (
            <div
              key={m.orgId}
              className="nav-item"
              style={{ margin: 0, background: m.orgId === active.orgId ? "var(--accent-soft)" : undefined, color: m.orgId === active.orgId ? "var(--accent)" : undefined }}
              onClick={(e) => {
                e.stopPropagation();
                onChange(m.orgId);
                setOpen(false);
              }}
            >
              <div className="org-avatar" style={{ width: 22, height: 22, fontSize: 11 }}>
                {m.org.name?.[0] ?? "?"}
              </div>
              <div className="org-meta">
                <div className="org-name" style={{ fontSize: 12.5 }}>
                  {m.org.name}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
