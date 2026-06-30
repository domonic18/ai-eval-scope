import { createContext, useContext, useEffect, useState } from "react"
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom"
import type { ReactNode } from "react"
import { api } from "@/api/client"
import { clearSession, getActiveOrg, loadSession, setActiveOrg, updateSessionUser } from "@/store/auth"
import { APP_VERSION } from "@/version"
import type { Membership } from "@/types"
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
import { useToast } from "@/components/toast"
import {
  Bell,
  BookOpen,
  ChevronDown,
  LayoutDashboard,
  Activity,
  Lock,
  LogOut,
  Users,
  Plus,
  Search,
  Trash2,
} from "lucide-react"

/** 面包屑：label + 可选回跳 to。 */
export interface Crumb {
  label: ReactNode
  to?: string
}
interface CrumbsApi {
  crumbs: Crumb[]
  setCrumbs: (c: Crumb[]) => void
}
interface OrgApi {
  activeOrg: string | null
  memberships: Membership[]
  loading: boolean
  setActive: (orgId: string) => void
}

const CrumbsContext = createContext<CrumbsApi>({ crumbs: [], setCrumbs: () => {} })
const OrgContext = createContext<OrgApi>({
  activeOrg: null,
  memberships: [],
  loading: true,
  setActive: () => {},
})

export const useCrumbs = () => useContext(CrumbsContext)
export const useOrg = () => useContext(OrgContext)

interface MemberRow {
  userId: string
  role: string
  email: string
  name: string | null
}
interface JoinRequestRow {
  id: string
  status: string
  message: string | null
  user: { id: string; email: string; name: string | null }
}

const NAV_MAIN = [
  { to: "/dashboard", icon: LayoutDashboard, label: "项目看板", match: (p: string) => p === "/dashboard" || p.startsWith("/project") },
  { to: "/runs", icon: Activity, label: "全部运行", match: (p: string) => p.startsWith("/run") },
]

export function AppShell() {
  const [memberships, setMemberships] = useState<Membership[]>([])
  const [activeOrg, setActive] = useState<string | null>(null)
  const [orgLoading, setOrgLoading] = useState(true)
  const [crumbs, setCrumbs] = useState<Crumb[]>([])
  const [createOrgOpen, setCreateOrgOpen] = useState(false)
  const [membersOpen, setMembersOpen] = useState(false)
  const [members, setMembers] = useState<MemberRow[]>([])
  const [joinRequests, setJoinRequests] = useState<JoinRequestRow[]>([])
  const [newOrgName, setNewOrgName] = useState("")
  const [inviteEmail, setInviteEmail] = useState("")
  const [creatingOrg, setCreatingOrg] = useState(false)
  const [inviting, setInviting] = useState(false)
  const [platformAdmin, setPlatformAdmin] = useState(!!loadSession()?.user?.platformAdmin)
  const toast = useToast()
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
  async function loadMembers() {
    if (!activeOrg) return
    try {
      setMembers(await api.listMembers(activeOrg))
    } catch {
      setMembers([])
    }
  }
  async function loadJoinRequests() {
    if (!activeOrg) return
    try {
      setJoinRequests(await api.orgJoinRequests(activeOrg))
    } catch {
      setJoinRequests([])
    }
  }
  async function openMembers() {
    setMembersOpen(true)
    await Promise.all([loadMembers(), loadJoinRequests()])
  }
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
  async function doInvite() {
    const email = inviteEmail.trim()
    if (!email || !activeOrg) return
    setInviting(true)
    try {
      await api.inviteMember(activeOrg, email, "member")
      setInviteEmail("")
      await loadMembers()
      toast.success("已添加成员")
    } catch (e) {
      const ex = e as { response?: { data?: { error?: string } }; message?: string }
      toast.error(ex.response?.data?.error || ex.message || "添加失败")
    } finally {
      setInviting(false)
    }
  }
  async function doRemoveMember(userId: string) {
    if (!activeOrg) return
    try {
      await api.removeMember(activeOrg, userId)
      await loadMembers()
      toast.success("已移除")
    } catch {
      toast.error("移除失败")
    }
  }
  async function doApprove(reqId: string) {
    if (!activeOrg) return
    try {
      await api.approveJoin(activeOrg, reqId)
      await Promise.all([loadJoinRequests(), loadMembers()])
      toast.success("已通过")
    } catch {
      toast.error("操作失败")
    }
  }
  async function doReject(reqId: string) {
    if (!activeOrg) return
    try {
      await api.rejectJoin(activeOrg, reqId)
      await loadJoinRequests()
      toast.success("已拒绝")
    } catch {
      toast.error("操作失败")
    }
  }

  const pendingRequests = joinRequests.filter((r) => r.status === "pending")

  return (
    <OrgContext.Provider value={{ activeOrg, memberships, loading: orgLoading, setActive: setActiveOrgId }}>
      <CrumbsContext.Provider value={{ crumbs, setCrumbs }}>
        <div className="flex min-h-screen bg-background text-foreground">
          {/* Sidebar */}
          <aside className="flex w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
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
              {/* 团队切换器 */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button className="flex w-full items-center justify-between gap-2 rounded-md border bg-secondary px-2.5 py-2 text-sm font-semibold text-secondary-foreground hover:bg-secondary/80">
                    <span className="flex min-w-0 items-center gap-2">
                      <Users className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">
                        {activeMembership?.org.name ?? "选择团队"}
                      </span>
                      {pendingRequests.length > 0 && <Badge>{pendingRequests.length}</Badge>}
                    </span>
                    <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
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
                    <DropdownMenuItem onClick={openMembers}>
                      <Users className="size-4" /> 成员管理
                      {pendingRequests.length > 0 && <Badge>{pendingRequests.length}</Badge>}
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <nav className="flex-1 space-y-1 p-3">
              {NAV_MAIN.map((it) => {
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
              })}
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
                to="/dashboard"
                className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              >
                <BookOpen className="size-4" />
                文档 &amp; 接入指引
              </Link>
            </div>
          </aside>

          {/* Main */}
          <div className="flex min-w-0 flex-1 flex-col">
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

        {/* 成员管理（owner）*/}
        <Dialog open={membersOpen} onOpenChange={setMembersOpen}>
          <DialogContent className="max-w-xl">
            <DialogHeader>
              <DialogTitle>成员管理</DialogTitle>
              <DialogDescription>{activeMembership?.org.name}</DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              {pendingRequests.length > 0 && (
                <div className="space-y-2 rounded-lg border bg-secondary/40 p-3">
                  <div className="text-sm font-medium">待审申请</div>
                  {pendingRequests.map((r) => (
                    <div key={r.id} className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm">
                        {r.user.email}
                        {r.message && <span className="text-muted-foreground"> — {r.message}</span>}
                      </span>
                      <div className="flex shrink-0 gap-2">
                        <Button size="sm" onClick={() => doApprove(r.id)}>
                          通过
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => doReject(r.id)}>
                          拒绝
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex gap-2">
                <Input
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="输入邮箱邀请（须已注册）"
                />
                <Button onClick={doInvite} disabled={inviting}>
                  {inviting ? "添加中…" : "邀请"}
                </Button>
              </div>
              {members.length === 0 ? (
                <div className="text-sm text-muted-foreground">暂无其他成员</div>
              ) : (
                <div className="divide-y">
                  {members.map((m) => (
                    <div key={m.userId} className="flex items-center justify-between py-2.5">
                      <span className="flex items-center gap-2 text-sm">
                        {m.email}
                        <Badge variant="secondary">{m.role}</Badge>
                      </span>
                      {m.role !== "owner" && m.userId !== session?.user.id && (
                        <Button variant="ghost" size="icon" title="移除" onClick={() => doRemoveMember(m.userId)}>
                          <Trash2 className="size-4" />
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <DialogFooter>
              <Button onClick={() => setMembersOpen(false)}>完成</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CrumbsContext.Provider>
    </OrgContext.Provider>
  )
}
