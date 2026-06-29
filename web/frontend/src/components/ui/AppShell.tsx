import { createContext, useContext, useEffect, useState } from "react"
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom"
import type { ReactNode } from "react"
import { api } from "../../api/client"
import { clearSession, getActiveOrg, loadSession, setActiveOrg } from "../../store/auth"
import type { Membership } from "../../types"
import { initialOf } from "../../lib/format"
import {
  IconBell,
  IconBook,
  IconChevronDown,
  IconDashboard,
  IconLogout,
  IconMembers,
  IconPlus,
  IconRuns,
  IconSearch,
  IconTrash,
} from "../icons"
import { Logo } from "./Logo"
import { Modal } from "./Modal"
import { Button } from "./Button"
import { Field, Input } from "./Field"
import { Badge } from "./atoms"
import { useToast } from "./Toast"
import { Dropdown, DropdownItem, DropdownSeparator, DropdownLabel } from "./Dropdown"

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
  setActive: (orgId: string) => void
}

const CrumbsContext = createContext<CrumbsApi>({ crumbs: [], setCrumbs: () => {} })
const OrgContext = createContext<OrgApi>({ activeOrg: null, memberships: [], setActive: () => {} })

export const useCrumbs = () => useContext(CrumbsContext)
export const useOrg = () => useContext(OrgContext)

interface NavItem {
  to: string
  icon: ReactNode
  label: string
  match: (path: string) => boolean
}

const NAV_MAIN: NavItem[] = [
  {
    to: "/dashboard",
    icon: <IconDashboard size={16} />,
    label: "项目看板",
    match: (p) => p === "/dashboard" || p.startsWith("/project"),
  },
  {
    to: "/runs",
    icon: <IconRuns size={16} />,
    label: "全部运行",
    match: (p) => p.startsWith("/run"),
  },
]

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

export function AppShell() {
  const [memberships, setMemberships] = useState<Membership[]>([])
  const [activeOrg, setActive] = useState<string | null>(null)
  const [crumbs, setCrumbs] = useState<Crumb[]>([])
  const [menuOpen, setMenuOpen] = useState(false)
  // 组织切换器 + 团队/成员管理弹窗
  const [orgMenuOpen, setOrgMenuOpen] = useState(false)
  const [createOrgOpen, setCreateOrgOpen] = useState(false)
  const [membersOpen, setMembersOpen] = useState(false)
  const [members, setMembers] = useState<MemberRow[]>([])
  const [joinRequests, setJoinRequests] = useState<JoinRequestRow[]>([])
  const [newOrgName, setNewOrgName] = useState("")
  const [inviteEmail, setInviteEmail] = useState("")
  const [creatingOrg, setCreatingOrg] = useState(false)
  const [inviting, setInviting] = useState(false)
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
      })
      .catch((e) => {
        // token 对应用户不存在（清库后旧 session 等）或 401 → 清 session 跳登录，
        // 避免旧 token 进入系统后下游（如 joinRequest.create）外键违反 500
        const status = (e as { response?: { status?: number } }).response?.status
        if (status === 401 || status === 404) {
          clearSession()
          nav("/login", { replace: true })
        }
      })
  }, [])

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
              {/* 团队切换器（workspace switcher 风格：容器感按钮 + 深色下拉 + 当前项高亮 + hover 反馈）*/}
              <div style={{ position: "relative", marginBottom: 14 }}>
                <button
                  onClick={() => setOrgMenuOpen((o) => !o)}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    padding: "8px 10px",
                    background: "var(--bg-surface)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--r-md)",
                    color: "var(--text-primary)",
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8, overflow: "hidden" }}>
                    <IconMembers size={15} style={{ color: "var(--text-secondary)", flexShrink: 0 }} />
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {activeMembership?.org.name ?? "选择团队"}
                    </span>
                    {pendingRequests.length > 0 && <Badge>{pendingRequests.length}</Badge>}
                  </span>
                  <IconChevronDown size={14} style={{ color: "var(--text-tertiary)", flexShrink: 0 }} />
                </button>
                {orgMenuOpen && (
                  <>
                    <div
                      style={{ position: "fixed", inset: 0, zIndex: 60 }}
                      onClick={() => setOrgMenuOpen(false)}
                    />
                    <div
                      style={{
                        position: "absolute",
                        top: "calc(100% + 6px)",
                        left: 0,
                        right: 0,
                        minWidth: 240,
                        background: "var(--bg-elevated)",
                        border: "1px solid var(--border)",
                        borderRadius: "var(--r-md)",
                        boxShadow: "var(--shadow-lg)",
                        padding: 6,
                        zIndex: 61,
                      }}
                    >
                      {memberships.map((m) => {
                        const active = m.orgId === activeOrg
                        return (
                          <button
                            key={m.orgId}
                            onClick={() => {
                              setActiveOrgId(m.orgId)
                              setOrgMenuOpen(false)
                            }}
                            style={{
                              width: "100%",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              gap: 8,
                              padding: "8px 10px",
                              background: active ? "var(--accent-soft)" : "transparent",
                              border: "none",
                              borderRadius: "var(--r-sm)",
                              color: active ? "var(--accent)" : "var(--text-primary)",
                              fontSize: 13,
                              fontWeight: active ? 600 : 500,
                              cursor: "pointer",
                            }}
                            onMouseEnter={(e) => {
                              if (!active) e.currentTarget.style.background = "var(--bg-hover)"
                            }}
                            onMouseLeave={(e) => {
                              if (!active) e.currentTarget.style.background = "transparent"
                            }}
                          >
                            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                              {m.org.name}
                            </span>
                            {m.role === "owner" && <Badge>owner</Badge>}
                          </button>
                        )
                      })}
                      <div style={{ borderTop: "1px solid var(--border)", margin: "6px 4px" }} />
                      {(
                        [
                          {
                            icon: <IconPlus size={15} />,
                            label: "创建团队",
                            onClick: () => {
                              setOrgMenuOpen(false)
                              setCreateOrgOpen(true)
                            },
                          },
                          {
                            icon: <IconMembers size={15} />,
                            label: "加入团队",
                            onClick: () => {
                              setOrgMenuOpen(false)
                              nav("/join")
                            },
                          },
                          ...(isOwner
                            ? [
                                {
                                  icon: <IconMembers size={15} />,
                                  label: "成员管理",
                                  onClick: () => {
                                    setOrgMenuOpen(false)
                                    openMembers()
                                  },
                                  badge: pendingRequests.length > 0 ? pendingRequests.length : null,
                                },
                              ]
                            : []),
                        ] as { icon: ReactNode; label: string; onClick: () => void; badge?: number | null }[]
                      ).map((it, i) => (
                        <button
                          key={i}
                          onClick={it.onClick}
                          style={{
                            width: "100%",
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            padding: "8px 10px",
                            background: "transparent",
                            border: "none",
                            borderRadius: "var(--r-sm)",
                            color: "var(--text-secondary)",
                            fontSize: 13,
                            cursor: "pointer",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = "var(--bg-hover)"
                            e.currentTarget.style.color = "var(--text-primary)"
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = "transparent"
                            e.currentTarget.style.color = "var(--text-secondary)"
                          }}
                        >
                          <span style={{ display: "inline-flex", color: "var(--text-tertiary)" }}>
                            {it.icon}
                          </span>
                          {it.label}
                          {it.badge ? <Badge>{it.badge}</Badge> : null}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
            <nav className="nav-section">
              {NAV_MAIN.map((it) => (
                <Link
                  key={it.to}
                  to={it.to}
                  className={`nav-item ${it.match(loc.pathname) ? "active" : ""}`}
                >
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
                        <span className={i === crumbs.length - 1 ? "current" : ""}>
                          {c.label}
                        </span>
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
                <Dropdown
                  open={menuOpen}
                  onClose={() => setMenuOpen(false)}
                  align="right"
                  width={220}
                  trigger={
                    <div className="avatar" onClick={() => setMenuOpen((o) => !o)}>
                      {initialOf(session?.user.name || session?.user.email)}
                    </div>
                  }
                >
                  <DropdownLabel>{session?.user.email}</DropdownLabel>
                  <DropdownSeparator />
                  <DropdownItem
                    variant="danger"
                    onClick={() => {
                      clearSession()
                      nav("/login")
                    }}
                  >
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                      <IconLogout size={15} />
                      登出
                    </span>
                  </DropdownItem>
                </Dropdown>
              </div>
            </header>

            <Outlet />
          </div>
        </div>

        {/* 创建团队 */}
        <Modal
          open={createOrgOpen}
          onClose={() => setCreateOrgOpen(false)}
          title="创建团队"
          desc="团队内所有成员共享该团队下的全部项目"
          footer={
            <>
              <Button onClick={() => setCreateOrgOpen(false)}>取消</Button>
              <Button variant="primary" onClick={doCreateOrg} disabled={creatingOrg}>
                {creatingOrg ? "创建中…" : "创建"}
              </Button>
            </>
          }
        >
          <Field label="团队名称">
            <Input
              value={newOrgName}
              onChange={(e) => setNewOrgName(e.target.value)}
              placeholder="如：课件评估组"
              autoFocus
            />
          </Field>
        </Modal>

        {/* 成员管理（owner）—— 含待审申请审批 + 邀请 + 成员列表 */}
        <Modal
          open={membersOpen}
          onClose={() => setMembersOpen(false)}
          title="成员管理"
          desc={activeMembership?.org.name}
          width={560}
          footer={
            <Button variant="primary" onClick={() => setMembersOpen(false)}>
              完成
            </Button>
          }
        >
          {/* 待审申请 */}
          {pendingRequests.length > 0 && (
            <div
              style={{
                marginBottom: 16,
                padding: 12,
                background: "var(--bg-surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>待审申请</div>
              {pendingRequests.map((r) => (
                <div
                  key={r.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "6px 0",
                  }}
                >
                  <span style={{ fontSize: 13, overflow: "hidden" }}>
                    {r.user.email}
                    {r.message ? (
                      <span style={{ color: "var(--text-tertiary)" }}> — {r.message}</span>
                    ) : null}
                  </span>
                  <span style={{ display: "flex", gap: 6 }}>
                    <Button size="sm" variant="primary" onClick={() => doApprove(r.id)}>
                      通过
                    </Button>
                    <Button size="sm" onClick={() => doReject(r.id)}>
                      拒绝
                    </Button>
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* 邀请（按 email 直接加）*/}
          <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
            <Input
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="输入邮箱邀请（须已注册）"
            />
            <Button variant="primary" onClick={doInvite} disabled={inviting}>
              {inviting ? "添加中…" : "邀请"}
            </Button>
          </div>

          {/* 成员列表 */}
          {members.length === 0 ? (
            <div style={{ color: "var(--text-tertiary)", fontSize: 13 }}>暂无其他成员</div>
          ) : (
            members.map((m) => (
              <div
                key={m.userId}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "8px 0",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                  <span>{m.email}</span>
                  <Badge>{m.role}</Badge>
                </span>
                {m.role !== "owner" && m.userId !== session?.user.id && (
                  <button className="icon-btn" title="移除" onClick={() => doRemoveMember(m.userId)}>
                    <IconTrash size={14} />
                  </button>
                )}
              </div>
            ))
          )}
        </Modal>
      </CrumbsContext.Provider>
    </OrgContext.Provider>
  )
}
