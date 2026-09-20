import { useCallback, useEffect, useState } from "react"
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom"
import { api } from "@/api/client"
import { clearSession, getActiveOrg, loadSession, setActiveOrg, updateSessionUser } from "@/store/auth"
import { APP_VERSION } from "@/version"
import type { JoinRequestRow, Membership } from "@/types"
import { initialOf } from "@/lib/format"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Label } from "@/components/shadcn/label"
import { Badge } from "@/components/shadcn/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/shadcn/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/shadcn/dropdown-menu"
import { useToast } from "@/hooks/useToast"
import { CrumbsContext, OrgContext, type Crumb } from "@/context/navigation"
import { useTheme } from "@/context/theme"
import {
  Bell,
  BookOpen,
  ChevronDown,
  LayoutDashboard,
  Lock,
  LogOut,
  Moon,
  Users,
  Plus,
  Search,
  Sun,
} from "lucide-react"

const NAV_MAIN = [
  { to: "/dashboard", icon: LayoutDashboard, label: "项目看板", match: (p: string) => p === "/dashboard" || p.startsWith("/project") },
]

const NAV_ORG = [
  { to: "/members", icon: Users, label: "成员", match: (p: string) => p.startsWith("/members") },
]

export function AppShell() {
  const [memberships, setMemberships] = useState<Membership[]>([])
  const [activeOrg, setActive] = useState<string | null>(null)
  const [orgLoading, setOrgLoading] = useState(true)
  const [crumbs, setCrumbs] = useState<Crumb[]>([])
  const [createOrgOpen, setCreateOrgOpen] = useState(false)
  const [joinRequests, setJoinRequests] = useState<JoinRequestRow[]>([])
  const [newOrgName, setNewOrgName] = useState("")
  const [creatingOrg, setCreatingOrg] = useState(false)
  const [platformAdmin, setPlatformAdmin] = useState(!!loadSession()?.user?.platformAdmin)
  const toast = useToast()
  const { theme, toggle } = useTheme()
  const nav = useNavigate()
  const loc = useLocation()
  const session = loadSession()

  useEffect(() => {
    api
      .me()
      .then((d) => {
        setMemberships(d.memberships)
        setActive(getActiveOrg(d.memberships))
        updateSessionUser({
          id: d.id,
          email: d.email,
          name: d.name,
          role: d.role,
          platformAdmin: d.platformAdmin,
          status: d.status,
        })
        setPlatformAdmin(!!d.platformAdmin)
      })
      .catch((e) => {
        const status = (e as { response?: { status?: number } }).response?.status
        if (status === 401 || status === 404) {
          clearSession()
          nav("/login", { replace: true })
        }
      })
      .finally(() => setOrgLoading(false))
  }, [nav])

  const setActiveOrgId = (orgId: string) => {
    setActive(orgId)
    setActiveOrg(orgId)
    nav("/dashboard")
  }

  const activeMembership = memberships.find((m) => m.orgId === activeOrg) ?? null
  const isOwner = activeMembership?.role === "owner"

  async function reloadMemberships() {
    const d = await api.me()
    setMemberships(d.memberships)
  }

  // 侧栏待审徽标：主动拉取（修复原先仅开 Dialog 才拉、徽标恒 0 的 bug）；
  // Members 页操作后广播 members:changed，这里监听重拉
  const refetchJoinRequests = useCallback(async () => {
    if (!activeOrg || !isOwner) return
    try {
      setJoinRequests(await api.orgJoinRequests(activeOrg))
    } catch {
      setJoinRequests([])
    }
  }, [activeOrg, isOwner])

  useEffect(() => {
    if (!activeOrg || !isOwner) {
      setJoinRequests([])
      return
    }
    refetchJoinRequests()
  }, [activeOrg, isOwner, refetchJoinRequests])

  useEffect(() => {
    window.addEventListener("members:changed", refetchJoinRequests)
    return () => window.removeEventListener("members:changed", refetchJoinRequests)
  }, [refetchJoinRequests])

  // 切换器副标题「Team · N 项目」（看板接口轻量复用，仅取数量）
  const [projectCount, setProjectCount] = useState(0)
  useEffect(() => {
    if (!activeOrg) return
    let cancelled = false
    api
      .dashboard(activeOrg)
      .then((ps) => {
        if (!cancelled) setProjectCount(ps.length)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [activeOrg])

  async function doCreateOrg() {
    const name = newOrgName.trim()
    if (!name) {
      toast.error("请填写团队名称")
      return
    }
    setCreatingOrg(true)
    try {
      const org = await api.createOrg(name)
      await reloadMemberships()
      setActiveOrgId(org.id)
      setCreateOrgOpen(false)
      setNewOrgName("")
      toast.success("团队已创建")
    } catch (e) {
      toast.error("创建失败：" + ((e as Error).message ?? ""))
    } finally {
      setCreatingOrg(false)
    }
  }

  const pendingRequests = joinRequests.filter((r) => r.status === "pending")

  /** 侧栏导航项（主导航 / 组织分组共用样式）。 */
  const renderNavItem = (it: {
    to: string
    icon: typeof LayoutDashboard
    label: string
    match: (p: string) => boolean
  }) => {
    const Icon = it.icon
    return (
      <Link
        key={it.to}
        to={it.to}
        className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
          it.match(loc.pathname)
            ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
            : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
        }`}
      >
        <Icon className="size-4" />
        {it.label}
      </Link>
    )
  }

  return (
    <OrgContext.Provider
      value={{ activeOrg, memberships, loading: orgLoading, setActive: setActiveOrgId, refresh: reloadMemberships }}
    >
      <CrumbsContext.Provider value={{ crumbs, setCrumbs }}>
        <div className="flex min-h-screen bg-background text-foreground">
          <div className="scanlines" aria-hidden />
          {/* Sidebar */}
          <aside className="relative z-10 flex w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
            <div className="border-b p-4">
              <Link to="/dashboard" className="mb-3 inline-flex items-center gap-2">
                <span className="flex size-7 items-center justify-center">
                  <img src="/logo.svg" alt="EvalScope" className="h-full w-full" />
                </span>
                <span className="font-semibold tracking-tight">EvalScope</span>
                <span className="rounded border border-border bg-secondary px-1 py-0.5 font-mono text-[10px] font-medium tracking-tight text-muted-foreground">
                  v{APP_VERSION}
                </span>
              </Link>
              {/* 团队切换器（对齐原型 .org-switcher：26px 渐变方标 + 团队名 + Team · N 项目） */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button className="flex w-full items-center gap-2.5 rounded-md border bg-secondary px-2.5 py-2 text-left transition-colors hover:border-primary/40">
                    <span
                      className="flex size-[26px] shrink-0 items-center justify-center rounded-sm text-xs font-bold text-white"
                      style={{ background: "linear-gradient(135deg, var(--accent-brand), var(--signal))" }}
                    >
                      {initialOf(activeMembership?.org.name ?? null)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-semibold leading-tight">
                        {activeMembership?.org.name ?? "选择团队"}
                      </span>
                      <span className="block text-[11px] leading-tight text-muted-foreground">
                        Team · {projectCount} 项目
                      </span>
                    </span>
                    {pendingRequests.length > 0 && <Badge>{pendingRequests.length}</Badge>}
                    <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-56" align="start">
                  {memberships.map((m) => (
                    <DropdownMenuItem
                      key={m.orgId}
                      onClick={() => setActiveOrgId(m.orgId)}
                      className={m.orgId === activeOrg ? "bg-accent text-accent-foreground" : ""}
                    >
                      <span className="flex-1 truncate">{m.org.name}</span>
                      {m.role === "owner" && <Badge variant="secondary">owner</Badge>}
                    </DropdownMenuItem>
                  ))}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => setCreateOrgOpen(true)}>
                    <Plus className="size-4" /> 创建团队
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => nav("/join")}>
                    <Users className="size-4" /> 加入团队
                  </DropdownMenuItem>
                  {isOwner && (
                    <DropdownMenuItem onClick={() => nav("/members")}>
                      <Users className="size-4" /> 成员管理
                      {pendingRequests.length > 0 && <Badge>{pendingRequests.length}</Badge>}
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <nav className="flex-1 space-y-1 p-3">
              {NAV_MAIN.map(renderNavItem)}
              <div className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                组织
              </div>
              {NAV_ORG.map(renderNavItem)}
              {platformAdmin && (
                <Link
                  to="/admin"
                  className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                    loc.pathname.startsWith("/admin")
                      ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                      : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
                  }`}
                >
                  <Lock className="size-4" />
                  管理后台
                </Link>
              )}
            </nav>
            <div className="border-t p-3">
              <Link
                to="/docs"
                className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              >
                <BookOpen className="size-4" />
                文档 &amp; 接入指引
              </Link>
            </div>
          </aside>

          {/* Main */}
          <div className="relative z-10 flex min-w-0 flex-1 flex-col">
            <header className="flex h-14 items-center justify-between border-b px-6">
              <div className="flex items-center gap-2 text-sm">
                {crumbs.length === 0 ? (
                  <span className="text-muted-foreground">EvalScope</span>
                ) : (
                  crumbs.map((c, i) => (
                    <span key={i} className="flex items-center gap-2">
                      {i > 0 && <span className="text-muted-foreground/50">/</span>}
                      {c.to && i < crumbs.length - 1 ? (
                        <Link to={c.to} className="text-muted-foreground hover:text-foreground">
                          {c.label}
                        </Link>
                      ) : (
                        <span className={i === crumbs.length - 1 ? "font-medium text-foreground" : "text-muted-foreground"}>
                          {c.label}
                        </span>
                      )}
                    </span>
                  ))
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  title={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
                  onClick={toggle}
                >
                  {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
                </Button>
                <Button variant="ghost" size="icon" title="搜索">
                  <Search className="size-4" />
                </Button>
                <Button variant="ghost" size="icon" title="通知">
                  <Bell className="size-4" />
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button className="flex size-8 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
                      {initialOf(session?.user.name || session?.user.email)}
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-56">
                    <DropdownMenuLabel>{session?.user.email}</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => {
                        clearSession()
                        nav("/login")
                      }}
                    >
                      <LogOut className="size-4" /> 登出
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </header>

            <Outlet />
          </div>
        </div>

        {/* 创建团队 */}
        <Dialog open={createOrgOpen} onOpenChange={setCreateOrgOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>创建团队</DialogTitle>
              <DialogDescription>团队内所有成员共享该团队下的全部项目</DialogDescription>
            </DialogHeader>
            <div className="space-y-2 py-2">
              <Label htmlFor="org-name">团队名称</Label>
              <Input
                id="org-name"
                value={newOrgName}
                onChange={(e) => setNewOrgName(e.target.value)}
                placeholder="如：课件评估组"
                autoFocus
              />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setCreateOrgOpen(false)}>
                取消
              </Button>
              <Button onClick={doCreateOrg} disabled={creatingOrg}>
                {creatingOrg ? "创建中…" : "创建"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CrumbsContext.Provider>
    </OrgContext.Provider>
  )
}
