/**
 * 成员管理页（docs/design/members.html 落地）：成员表格 + 邀请 + 待审申请 + 角色管理。
 * 页面对全员开放（GET members 成员可读）；管理操作仅 owner 可见（后端 orgGuard 强制）。
 */
import { useEffect, useState } from "react"
import { api } from "../api/client"
import type { JoinRequestRow, MemberRow, OrgInvitationRow } from "../types"
import { fmtDateTime, initialOf, timeAgo } from "../lib/format"
import { loadSession } from "../store/auth"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Label } from "@/components/shadcn/label"
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/shadcn/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/shadcn/select"
import {
  DataTable,
  Page,
  PageHead,
  SectionCard,
  SectionCardContent,
  SectionCardHeader,
  SectionCardTitle,
  type Column,
} from "../components/shared"
import { useCrumbs, useOrg } from "../context/navigation"
import { useToast } from "../hooks/useToast"
import { UserCheck, UserMinus, UserPlus } from "lucide-react"

/** 邮箱 hash 取渐变底色（头像无图，纯色即可区分）。 */
const AVATAR_GRADIENTS = [
  "from-violet-500 to-indigo-500",
  "from-sky-500 to-cyan-500",
  "from-emerald-500 to-teal-500",
  "from-amber-500 to-orange-500",
  "from-rose-500 to-pink-500",
  "from-fuchsia-500 to-purple-500",
]
function gradientOf(seed: string): string {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  return AVATAR_GRADIENTS[h % AVATAR_GRADIENTS.length]
}

type ConfirmAction = "promote" | "transfer" | "demote" | "remove"

export default function Members() {
  const { activeOrg, memberships, refresh } = useOrg()
  const { setCrumbs } = useCrumbs()
  const toast = useToast()
  const session = loadSession()
  const selfId = session?.user.id

  const membership = memberships.find((m) => m.orgId === activeOrg) ?? null
  const isOwner = membership?.role === "owner"
  const orgName = membership?.org.name ?? "团队"

  const [members, setMembers] = useState<MemberRow[] | null>(null)
  const [invitations, setInvitations] = useState<OrgInvitationRow[]>([])
  const [requests, setRequests] = useState<JoinRequestRow[]>([])
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState("")
  const [inviteRole, setInviteRole] = useState("member")
  const [inviting, setInviting] = useState(false)
  const [confirm, setConfirm] = useState<{ type: ConfirmAction; target: MemberRow } | null>(null)
  const [acting, setActing] = useState(false)

  useEffect(() => {
    setCrumbs([{ label: orgName, to: "/dashboard" }, { label: "成员" }])
  }, [orgName, setCrumbs])

  const pending = requests.filter((r) => r.status === "pending")

  async function load() {
    if (!activeOrg) return
    try {
      setMembers(await api.listMembers(activeOrg))
    } catch {
      setMembers([])
    }
    if (isOwner) {
      try {
        setRequests(await api.orgJoinRequests(activeOrg))
      } catch {
        setRequests([])
      }
      try {
        setInvitations(await api.listInvitations(activeOrg))
      } catch {
        setInvitations([])
      }
    }
  }

  useEffect(() => {
    setMembers(null)
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOrg, isOwner])

  /** 管理操作后广播（侧栏徽标重拉）。 */
  function notifyChanged() {
    window.dispatchEvent(new CustomEvent("members:changed"))
  }

  function displayName(m: MemberRow): string {
    return m.name || m.email
  }

  async function doInvite() {
    if (!activeOrg) return
    const email = inviteEmail.trim()
    if (!email) {
      toast.error("请填写邮箱")
      return
    }
    setInviting(true)
    try {
      const result = await api.inviteMember(activeOrg, email, inviteRole)
      toast.success(
        result.kind === "member"
          ? `已添加 ${email}`
          : `邀请已发送至 ${email}，对方注册后将自动加入`,
      )
      setInviteOpen(false)
      setInviteEmail("")
      setInviteRole("member")
      await load()
      notifyChanged()
    } catch (e) {
      const ex = e as { response?: { status?: number; data?: { error?: string } }; message?: string }
      const msg =
        ex.response?.status === 409
          ? "该邮箱已是成员或已有待接受邀请"
          : (ex.response?.data?.error ?? ex.message ?? "邀请失败")
      toast.error(msg)
    } finally {
      setInviting(false)
    }
  }

  async function doConfirm() {
    if (!confirm || !activeOrg) return
    const { type, target } = confirm
    setActing(true)
    try {
      if (type === "remove") {
        await api.removeMember(activeOrg, target.userId)
        toast.success(`已移除 ${displayName(target)}`)
      } else if (type === "promote") {
        await api.updateMemberRole(activeOrg, target.userId, "owner")
        toast.success(`${displayName(target)} 已设为 Owner`)
      } else if (type === "transfer") {
        await api.updateMemberRole(activeOrg, target.userId, "owner", true)
        toast.success(`所有权已转移给 ${displayName(target)}`)
        await refresh()
      } else {
        await api.updateMemberRole(activeOrg, target.userId, "member")
        toast.success(`${displayName(target)} 已设为 Member`)
      }
      setConfirm(null)
      await load()
      notifyChanged()
    } catch (e) {
      const ex = e as { response?: { data?: { error?: string } }; message?: string }
      toast.error(ex.response?.data?.error ?? ex.message ?? "操作失败")
    } finally {
      setActing(false)
    }
  }

  async function doApprove(reqId: string) {
    if (!activeOrg) return
    try {
      await api.approveJoin(activeOrg, reqId)
      toast.success("已通过申请")
      await load()
      notifyChanged()
    } catch {
      toast.error("操作失败")
    }
  }

  async function doReject(reqId: string) {
    if (!activeOrg) return
    try {
      await api.rejectJoin(activeOrg, reqId)
      toast.success("已驳回申请")
      await load()
    } catch {
      toast.error("操作失败")
    }
  }

  async function doResendInvitation(inv: OrgInvitationRow) {
    if (!activeOrg) return
    try {
      await api.resendInvitation(activeOrg, inv.id)
      toast.success(`已向 ${inv.email} 重发邀请`)
      await load()
    } catch {
      toast.error("操作失败")
    }
  }

  async function doRevokeInvitation(inv: OrgInvitationRow) {
    if (!activeOrg) return
    try {
      await api.revokeInvitation(activeOrg, inv.id)
      toast.success(`已撤回对 ${inv.email} 的邀请`)
      await load()
    } catch {
      toast.error("操作失败")
    }
  }

  const roleTag = (role: string) =>
    role === "owner" ? (
      // 对齐原型 .role-tag.role-owner（品牌蓝软底；注意 --accent 是 shadcn hover 令牌，须用 --accent-brand）
      <span className="inline-flex items-center rounded-full bg-[var(--accent-soft)] px-[9px] py-[2px] text-[11px] font-semibold whitespace-nowrap text-[var(--accent-brand)]">
        Owner
      </span>
    ) : (
      <span className="inline-flex items-center rounded-full border border-border bg-secondary px-[9px] py-[2px] text-[11px] font-semibold whitespace-nowrap text-muted-foreground">
        Member
      </span>
    )
  const sorted = [...(members ?? [])].sort((a, b) => {
    if (a.role !== b.role) return a.role === "owner" ? -1 : 1
    return a.joinedAt.localeCompare(b.joinedAt)
  })

  const columns: Column<MemberRow>[] = [
    {
      key: "member",
      title: "成员",
      render: (m) => (
        <div className="flex items-center gap-3">
          <span
            className={`flex size-[34px] shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-[13px] font-semibold text-white ${gradientOf(m.email)}`}
          >
            {initialOf(m.name || m.email)}
          </span>
          <span className="min-w-0">
            <span className="flex items-center gap-1.5 text-[13.5px] font-[550]">
              <span className="truncate">{m.name || m.email.split("@")[0]}</span>
              {m.userId === selfId && (
                <span className="shrink-0 font-normal text-muted-foreground">（你）</span>
              )}
            </span>
            <span className="block truncate text-xs text-muted-foreground">{m.email}</span>
          </span>
        </div>
      ),
    },
    {
      key: "role",
      title: "角色",
      render: (m) => roleTag(m.role),
    },
    {
      key: "joinedAt",
      title: "加入时间",
      render: (m) => (
        <span className="text-[13px] text-muted-foreground">{fmtDateTime(m.joinedAt).slice(0, 10)}</span>
      ),
    },
    {
      key: "lastActive",
      title: "最近活跃",
      render: (m) => (
        <span className="text-[13px] text-muted-foreground">
          {m.lastActive ? timeAgo(m.lastActive) : "—"}
        </span>
      ),
    },
    ...(isOwner
      ? [
          {
            key: "actions",
            title: "",
            className: "w-20 text-right",
            render: (m: MemberRow) =>
              m.userId === selfId ? null : (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    {/* 对齐原型 .btn.btn-sm「管理」文字按钮；须用原生 button（项目 Button 不转发 ref，asChild 挂不上事件） */}
                    <button
                      type="button"
                      className="inline-flex h-7 items-center rounded-md border border-border bg-transparent px-2.5 text-xs font-medium transition-colors hover:bg-secondary"
                    >
                      管理
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-44">
                    {m.role === "member" && (
                      <DropdownMenuItem onClick={() => setConfirm({ type: "promote", target: m })}>
                        <UserPlus className="size-4" /> 设为 Owner
                      </DropdownMenuItem>
                    )}
                    <DropdownMenuItem onClick={() => setConfirm({ type: "transfer", target: m })}>
                      <UserCheck className="size-4" /> 转移所有权
                    </DropdownMenuItem>
                    {m.role === "owner" && (
                      <DropdownMenuItem onClick={() => setConfirm({ type: "demote", target: m })}>
                        <UserMinus className="size-4" /> 设为 Member
                      </DropdownMenuItem>
                    )}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => setConfirm({ type: "remove", target: m })}
                    >
                      <UserMinus className="size-4" /> 移除成员
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ),
          } satisfies Column<MemberRow>,
        ]
      : []),
  ]

  const confirmCopy: Record<ConfirmAction, { title: string; description: string; action: string }> = {
    promote: {
      title: "设为 Owner",
      description: `将 ${confirm ? displayName(confirm.target) : ""} 提升为 Owner，你们将共同拥有成员管理权限。`,
      action: "确认提升",
    },
    transfer: {
      title: "转移所有权",
      description: `${confirm ? displayName(confirm.target) : ""} 将成为 Owner。转移后你将失去成员管理与组织设置权限。`,
      action: "确认转移",
    },
    demote: {
      title: "设为 Member",
      description: `将 ${confirm ? displayName(confirm.target) : ""} 降级为 Member，其将失去成员管理权限。`,
      action: "确认降级",
    },
    remove: {
      title: "移除成员",
      description: `确定将 ${confirm ? displayName(confirm.target) : ""} 移出团队？其将无法访问团队下的全部项目。${
        confirm?.target.role === "owner" ? "该成员当前为 Owner。" : ""
      }`,
      action: "确认移除",
    },
  }

  return (
    <Page>
      <PageHead
        title="成员"
        sub={`管理组织成员及其角色 · 共 ${members?.length ?? 0} 人`}
        right={
          isOwner ? (
            <Button onClick={() => setInviteOpen(true)}>
              <UserPlus className="size-4" /> 邀请成员
            </Button>
          ) : undefined
        }
      />

      {isOwner && pending.length > 0 && (
        <SectionCard>
          <SectionCardHeader>
            <SectionCardTitle>待处理申请（{pending.length}）</SectionCardTitle>
          </SectionCardHeader>
          <SectionCardContent className="space-y-3">
            {pending.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-3">
                <div className="min-w-0 text-sm">
                  <span className="font-medium">{r.user.name || r.user.email}</span>
                  {r.user.name && (
                    <span className="ml-2 text-xs text-muted-foreground">{r.user.email}</span>
                  )}
                  {r.message && (
                    <span className="ml-2 text-xs text-muted-foreground">留言：{r.message}</span>
                  )}
                  <span className="ml-2 text-xs text-muted-foreground/70">
                    {timeAgo(r.createdAt)}
                  </span>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button size="sm" onClick={() => doApprove(r.id)}>
                    通过
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => doReject(r.id)}>
                    驳回
                  </Button>
                </div>
              </div>
            ))}
          </SectionCardContent>
        </SectionCard>
      )}

      {/* 对齐原型 table.data：表头 11px/600 大写 + 0.04em 字距 + surface 底；单元格 13px、16/12px 内边距 */}
      <div className="[&_td]:px-4 [&_td]:py-3 [&_td]:text-[13px] [&_th]:h-auto [&_th]:bg-secondary/60 [&_th]:px-4 [&_th]:py-2.5 [&_th]:text-[11px] [&_th]:font-semibold [&_th]:tracking-[0.04em] [&_th]:text-muted-foreground [&_th]:uppercase">
        <DataTable
          columns={columns}
          rows={sorted}
          rowKey={(m) => m.userId}
          empty={members === null ? "加载中…" : "暂无成员"}
        />
      </div>

      {/* 待接受邀请（原型 r-3 区块：13px/600 标题 + 独立表格） */}
      {isOwner && invitations.length > 0 && (
        <>
          <h3 className="mb-2.5 mt-3 text-[13px] font-semibold text-muted-foreground">
            待接受邀请（{invitations.length}）
          </h3>
          <div className="[&_td]:px-4 [&_td]:py-3 [&_td]:text-[13px] [&_th]:h-auto [&_th]:bg-secondary/60 [&_th]:px-4 [&_th]:py-2.5 [&_th]:text-[11px] [&_th]:font-semibold [&_th]:tracking-[0.04em] [&_th]:text-muted-foreground [&_th]:uppercase">
            <DataTable
              columns={[
                {
                  key: "email",
                  title: "邮箱",
                  render: (inv) => <span className="font-mono text-[12.5px]">{inv.email}</span>,
                },
                {
                  key: "role",
                  title: "角色",
                  render: (inv) => roleTag(inv.role),
                },
                {
                  key: "invitedAt",
                  title: "邀请时间",
                  render: (inv) => (
                    <span className="text-[13px] text-muted-foreground">
                      {timeAgo(inv.resentAt ?? inv.createdAt)} · {inv.inviter.name || inv.inviter.email} 邀请
                    </span>
                  ),
                },
                {
                  key: "actions",
                  title: "",
                  className: "w-40 text-right",
                  render: (inv) => (
                    <div className="flex justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={() => doResendInvitation(inv)}
                        className="inline-flex h-7 items-center rounded-md border border-border bg-transparent px-2.5 text-xs font-medium transition-colors hover:bg-secondary"
                      >
                        重发
                      </button>
                      <button
                        type="button"
                        onClick={() => doRevokeInvitation(inv)}
                        className="inline-flex h-7 items-center rounded-md bg-[var(--danger-soft)] px-2.5 text-xs font-semibold text-[var(--danger)] transition-opacity hover:opacity-80"
                      >
                        撤回
                      </button>
                    </div>
                  ),
                },
              ]}
              rows={invitations}
              rowKey={(inv) => inv.id}
              empty="暂无待接受邀请"
            />
          </div>
        </>
      )}

      {/* 邀请成员 */}
      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>邀请成员</DialogTitle>
            <DialogDescription>
              通过邮箱邀请成员加入组织；未注册邮箱将在对方注册后自动加入
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="invite-email">邮箱</Label>
              <Input
                id="invite-email"
                type="email"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="name@company.com"
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label>角色</Label>
              <Select value={inviteRole} onValueChange={setInviteRole}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="member">
                    <span className="font-medium">Member</span>
                    <span className="ml-2 text-xs text-muted-foreground">
                      可查看项目与运行数据
                    </span>
                  </SelectItem>
                  <SelectItem value="owner">
                    <span className="font-medium">Owner</span>
                    <span className="ml-2 text-xs text-muted-foreground">
                      可管理成员、项目与组织设置
                    </span>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setInviteOpen(false)}>
              取消
            </Button>
            <Button onClick={doInvite} disabled={inviting}>
              {inviting ? "邀请中…" : "发送邀请"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 确认弹窗（promote / transfer / demote / remove 状态机） */}
      <Dialog open={!!confirm} onOpenChange={(open) => !open && setConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{confirm ? confirmCopy[confirm.type].title : ""}</DialogTitle>
            <DialogDescription>{confirm ? confirmCopy[confirm.type].description : ""}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(null)}>
              取消
            </Button>
            <Button
              variant={confirm?.type === "remove" ? "destructive" : "default"}
              onClick={doConfirm}
              disabled={acting}
            >
              {acting ? "处理中…" : confirm ? confirmCopy[confirm.type].action : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  )
}
