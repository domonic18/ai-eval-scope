/**
 * 超管后台布局（独立 shell，不复用 AppShell——避免与组织上下文耦合）。
 * 左侧栏：总览 / 用户 / 工作组 / 项目 / 评估任务 / 产出物 / 审计。
 * 顶栏：logo + 返回主应用 + 当前账号 + 登出。
 * 参照 SquadSight AdminLayout 的 IA；样式沿用设计系统变量。
 */
import { useEffect } from "react"
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom"
import { clearSession, loadSession } from "../../store/auth"
import { Logo } from "../../components/ui"
import {
  IconArrowLeft,
  IconDashboard,
  IconMembers,
  IconKey,
  IconRuns,
  IconFile,
  IconDownload,
  IconEye,
  IconLogout,
} from "../../components/icons"

const NAV = [
  { to: "/admin", label: "总览", icon: <IconDashboard size={16} />, exact: true },
  { to: "/admin/users", label: "用户管理", icon: <IconMembers size={16} /> },
  { to: "/admin/orgs", label: "工作组", icon: <IconKey size={16} /> },
  { to: "/admin/projects", label: "项目管理", icon: <IconFile size={16} /> },
  { to: "/admin/runs", label: "评估任务", icon: <IconRuns size={16} /> },
  { to: "/admin/artifacts", label: "产出物", icon: <IconDownload size={16} /> },
  { to: "/admin/audit", label: "审计日志", icon: <IconEye size={16} /> },
]

export default function AdminLayout() {
  const loc = useLocation()
  const nav = useNavigate()
  const session = loadSession()

  useEffect(() => {
    document.title = "管理后台 · Agent Eval"
  }, [])

  const isActive = (to: string, exact?: boolean) =>
    exact ? loc.pathname === to : loc.pathname.startsWith(to)

  return (
    <div className="shell">
      <div className="ambient" />
      <div className="scanlines" />
      <aside className="sidebar">
        <div className="sidebar-head">
          <div style={{ marginBottom: 14 }}>
            <Logo />
          </div>
          <div
            style={{
              fontSize: 11,
              letterSpacing: 1,
              textTransform: "uppercase",
              color: "var(--text-tertiary)",
            }}
          >
            管理后台 · 超级管理员
          </div>
        </div>
        <nav className="nav-section">
          {NAV.map((it) => (
            <Link key={it.to} to={it.to} className={`nav-item ${isActive(it.to, it.exact) ? "active" : ""}`}>
              {it.icon}
              {it.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-foot">
          <Link to="/dashboard" className="nav-item">
            <IconArrowLeft size={16} />
            返回主应用
          </Link>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="topbar-left" style={{ fontWeight: 600 }}>
            平台管理
          </div>
          <div className="topbar-right">
            <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>
              {session?.user?.email}
            </span>
            <button
              className="btn btn-sm"
              onClick={() => {
                clearSession()
                nav("/login", { replace: true })
              }}
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              <IconLogout size={14} /> 登出
            </button>
          </div>
        </header>
        <Outlet />
      </div>
    </div>
  )
}
