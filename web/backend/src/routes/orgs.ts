/**
 * 组织路由（/api/v1/orgs/:org）。
 *  - 成员管理：GET /members（成员可读）；POST /members、PATCH|DELETE /members/:userId（owner）
 *  - 邀请（owner）：GET /invitations，POST /invitations/:id/{resend,revoke}
 *    （POST /members 对未注册邮箱自动转为待接受邀请，注册后自动加入）
 *  - 组织下项目：GET/POST /projects
 *
 * requireAuth → req.user；orgGuard → 校验成员关系并注入 req.tenant。
 */

import { Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { orgGuard } from "../middleware/tenantGuard"
import { createOrgService, createTeamOrg } from "../services/org.service"
import { createProjectService } from "../services/project.service"
import { createQueryService } from "../services/query.service"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

// 创建团队 Org（顺序：必须在 /:org/* 之前，否则 "orgs" 被 :org param 捕获）
router.post(
  "/",
  requireAuth,
  wrap(async (req, res) => {
    const org = await createTeamOrg({
      userId: req.user!.userId,
      ...(req.body?.name ? { name: req.body.name } : {}),
    })
    res.status(201).json({ org })
  }),
)

// 成员列表放宽为成员可读（成员页对全员开放；管理操作仍 owner-only）
router.get(
  "/:org/members",
  requireAuth,
  orgGuard(),
  wrap(async (req, res) => {
    const svc = createOrgService(req.tenant!)
    res.json({ members: await svc.listMembers() })
  }),
)

router.post(
  "/:org/members",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createOrgService(req.tenant!)
    const member = await svc.inviteMember(req.body || {})
    res.status(201).json({ member })
  }),
)

router.delete(
  "/:org/members/:userId",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createOrgService(req.tenant!)
    res.json(await svc.removeMember(req.params.userId))
  }),
)

// 角色变更 / 所有权转移（demoteSelf：提升他人同时降级自己，事务原子）
router.patch(
  "/:org/members/:userId",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createOrgService(req.tenant!)
    res.json(await svc.updateMemberRole(req.params.userId, req.body || {}))
  }),
)

// 待接受邀请（owner）：列表 / 重发 / 撤回
router.get(
  "/:org/invitations",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createOrgService(req.tenant!)
    res.json({ invitations: await svc.listInvitations() })
  }),
)

router.post(
  "/:org/invitations/:id/resend",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createOrgService(req.tenant!)
    res.json(await svc.resendInvitation(req.params.id))
  }),
)

router.post(
  "/:org/invitations/:id/revoke",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createOrgService(req.tenant!)
    res.json(await svc.revokeInvitation(req.params.id))
  }),
)

router.get(
  "/:org/projects",
  requireAuth,
  orgGuard(),
  wrap(async (req, res) => {
    // 看板：每项目最新运行指标 + 运行总数（§九）。archived=1 时回退到普通列表。
    if (req.query.archived === "1") {
      const svc = createProjectService(req.tenant!)
      res.json({ projects: await svc.list({ includeArchived: true }) })
      return
    }
    const q = createQueryService(req.tenant!)
    res.json({ projects: await q.dashboard() })
  }),
)

router.post(
  "/:org/projects",
  requireAuth,
  orgGuard(),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!)
    const project = await svc.create(req.body || {})
    res.status(201).json({ project })
  }),
)

export default router
