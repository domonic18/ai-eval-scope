/**
 * 超管后台布局（shadcn/Tailwind 重写）。
 * 左侧栏 + 顶栏；独立 shell，不复用主 AppShell（避免组织上下文耦合）。
 */
import { useEffect } from "react"
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom"
import { clearSession, loadSession } from "../../store/auth"
import { Button } from "@/components/shadcn/button"
import {
  LayoutDashboard,
  Users,
  KeyRound,
  FileText,
  Activity,
  Download,
  Eye,
  LogOut,
  ArrowLeft,
} from "lucide-react"

const NAV = [
  { to: "/admin", label: "总览", icon: LayoutDashboard, exact: true },
  { to: "/admin/users", label: "用户管理", icon: Users },
  { to: "/admin/orgs", label: "工作组", icon: KeyRound },
  { to: "/admin/projects", label: "项目管理", icon: FileText },
  { to: "/admin/runs", label: "评估任务", icon: Activity },
  { to: "/admin/artifacts", label: "产出物", icon: Download },
  { to: "/admin/audit", label: "审计日志", icon: Eye },
]

export default function AdminLayout() {
  const loc = useLocation()
  const nav = useNavigate()
  const session = loadSession()

  useEffect(() => {
    document.title = "管理后台 · EvalScope"
  }, [])

  const isActive = (to: string, exact?: boolean) =>
    exact ? loc.pathname === to : loc.pathname.startsWith(to)

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="flex w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
        <div className="border-b p-4">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-md bg-primary font-bold text-primary-foreground">
              E
            </div>
            <span className="font-semibold tracking-tight">EvalScope</span>
          </div>
          <div className="mt-3 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            管理后台 · 超级管理员
          </div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV.map((it) => {
            const Icon = it.icon
            return (
              <Link
                key={it.to}
                to={it.to}
                className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive(it.to, it.exact)
                    ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                    : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
                }`}
              >
                <Icon className="size-4" />
                {it.label}
              </Link>
            )
          })}
        </nav>
        <div className="border-t p-3">
          <Link
            to="/dashboard"
            className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
          >
            <ArrowLeft className="size-4" />
            返回主应用
          </Link>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b px-6">
          <div className="font-semibold">平台管理</div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">{session?.user?.email}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                clearSession()
                nav("/login", { replace: true })
              }}
            >
              <LogOut className="size-4" /> 登出
            </Button>
          </div>
        </header>
        <Outlet />
      </div>
    </div>
  )
}
