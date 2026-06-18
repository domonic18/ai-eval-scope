import { createContext, useContext, useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { api } from "../../api/client";
import { clearSession, getActiveOrg, loadSession, setActiveOrg } from "../../store/auth";
import type { Membership } from "../../types";
import { initialOf } from "../../lib/format";
import {
  IconBell,
  IconBook,
  IconDashboard,
  IconLogout,
  IconMembers,
  IconRuns,
  IconSearch,
  IconSettings,
} from "../icons";
import { Logo } from "./Logo";
import { OrgSwitcher } from "./OrgSwitcher";

/** 面包屑：label + 可选回跳 to。 */
export interface Crumb {
  label: ReactNode;
  to?: string;
}
interface CrumbsApi {
  crumbs: Crumb[];
  setCrumbs: (c: Crumb[]) => void;
}
interface OrgApi {
  activeOrg: string | null;
  memberships: Membership[];
  setActive: (orgId: string) => void;
}

const CrumbsContext = createContext<CrumbsApi>({ crumbs: [], setCrumbs: () => {} });
const OrgContext = createContext<OrgApi>({ activeOrg: null, memberships: [], setActive: () => {} });

export const useCrumbs = () => useContext(CrumbsContext);
export const useOrg = () => useContext(OrgContext);

interface NavItem {
  to: string;
  icon: ReactNode;
  label: string;
  match: (path: string) => boolean;
}

const NAV_MAIN: NavItem[] = [
  { to: "/dashboard", icon: <IconDashboard size={16} />, label: "项目看板", match: (p) => p === "/dashboard" || p.startsWith("/project") },
  { to: "/runs", icon: <IconRuns size={16} />, label: "全部运行", match: (p) => p.startsWith("/run") },
];
const NAV_ORG: NavItem[] = [
  { to: "/members", icon: <IconMembers size={16} />, label: "成员", match: (p) => p.startsWith("/members") },
  { to: "/settings", icon: <IconSettings size={16} />, label: "组织设置", match: (p) => p.startsWith("/settings") },
];

export function AppShell() {
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [activeOrg, setActive] = useState<string | null>(null);
  const [crumbs, setCrumbs] = useState<Crumb[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const nav = useNavigate();
  const loc = useLocation();
  const session = loadSession();

  useEffect(() => {
    api
      .me()
      .then((d) => {
        setMemberships(d.memberships);
        setActive(getActiveOrg(d.memberships));
      })
      .catch(() => {});
  }, []);

  const setActiveOrgId = (orgId: string) => {
    setActive(orgId);
    setActiveOrg(orgId);
    nav("/dashboard");
  };

  return (
    <OrgContext.Provider value={{ activeOrg, memberships, setActive: setActiveOrgId }}>
      <CrumbsContext.Provider value={{ crumbs, setCrumbs }}>
        <div className="shell">
          <div className="ambient" />
          <div className="scanlines" />

          {/* Sidebar */}
          <aside className="sidebar">
            <div className="sidebar-head">
              <div style={{ marginBottom: 14 }}>
                <Logo />
              </div>
              <OrgSwitcher memberships={memberships} activeOrg={activeOrg} onChange={setActiveOrgId} />
            </div>
            <nav className="nav-section">
              {NAV_MAIN.map((it) => (
                <Link key={it.to} to={it.to} className={`nav-item ${it.match(loc.pathname) ? "active" : ""}`}>
                  {it.icon}
                  {it.label}
                </Link>
              ))}
              <div className="nav-label">组织</div>
              {NAV_ORG.map((it) => (
                <Link key={it.to} to={it.to} className={`nav-item ${it.match(loc.pathname) ? "active" : ""}`}>
                  {it.icon}
                  {it.label}
                </Link>
              ))}
            </nav>
            <div className="sidebar-foot">
              <Link to="/dashboard" className="nav-item">
                <IconBook size={16} />
                文档 &amp; 接入指引
              </Link>
            </div>
          </aside>

          {/* Main */}
          <div className="main">
            <header className="topbar">
              <div className="crumbs">
                {crumbs.length === 0 ? (
                  <span className="muted">EvalScope</span>
                ) : (
                  crumbs.map((c, i) => (
                    <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                      {i > 0 && <span className="sep">/</span>}
                      {c.to && i < crumbs.length - 1 ? (
                        <Link to={c.to}>{c.label}</Link>
                      ) : (
                        <span className={i === crumbs.length - 1 ? "current" : ""}>{c.label}</span>
                      )}
                    </span>
                  ))
                )}
              </div>
              <div className="topbar-right">
                <button className="icon-btn" title="搜索">
                  <IconSearch size={16} />
                </button>
                <button className="icon-btn" title="通知">
                  <IconBell size={16} />
                </button>
                <div style={{ position: "relative" }}>
                  <div className="avatar" onClick={() => setMenuOpen((o) => !o)}>
                    {initialOf(session?.user.name || session?.user.email)}
                  </div>
                  {menuOpen && (
                    <>
                      <div style={{ position: "fixed", inset: 0, zIndex: 60 }} onClick={() => setMenuOpen(false)} />
                      <div
                        style={{
                          position: "absolute",
                          top: "calc(100% + 8px)",
                          right: 0,
                          minWidth: 200,
                          background: "var(--bg-elevated)",
                          border: "1px solid var(--border-hover)",
                          borderRadius: 8,
                          boxShadow: "var(--shadow-lg)",
                          padding: 8,
                          zIndex: 61,
                        }}
                      >
                        <div style={{ padding: "6px 10px", fontSize: 12, color: "var(--text-tertiary)" }}>
                          {session?.user.email}
                        </div>
                        <button
                          className="nav-item"
                          style={{ width: "100%", margin: 0 }}
                          onClick={() => {
                            clearSession();
                            nav("/login");
                          }}
                        >
                          <IconLogout size={16} />
                          登出
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </header>

            <Outlet />
          </div>
        </div>
      </CrumbsContext.Provider>
    </OrgContext.Provider>
  );
}
