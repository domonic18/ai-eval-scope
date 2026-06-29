/**
 * 团队发现 + 加入申请/审批路由（挂 /api/v1）。
 *
 *  GET    /teams                              列出所有团队（发现）+ 我的成员/申请状态
 *  GET    /me/join-requests                   我的加入申请
 *  POST   /orgs/:org/join-requests            申请加入（非成员，手动校验，不用 orgGuard）
 *  GET    /orgs/:org/join-requests            owner 看本团队申请
 *  POST   /orgs/:org/join-requests/:id/approve   owner 批准
 *  POST   /orgs/:org/join-requests/:id/reject    owner 拒绝
 */

import { Router, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { orgGuard } from "../middleware/tenantGuard"
import { JoinService } from "../services/join.service"

const router = Router()

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

// 列出所有团队（发现）
router.get(
  "/teams",
  requireAuth,
  wrap(async (req, res) => {
    res.json({ teams: await JoinService.listTeams(req.user!.userId) })
  }),
)

// 我的加入申请
router.get(
  "/me/join-requests",
  requireAuth,
  wrap(async (req, res) => {
    res.json({ requests: await JoinService.listMyRequests(req.user!.userId) })
  }),
)

// 申请加入（申请者非成员，不用 orgGuard；service 内手动校验 org 存在 + 非成员 + 无既有申请）
router.post(
  "/orgs/:org/join-requests",
  requireAuth,
  wrap(async (req, res) => {
    const request = await JoinService.requestJoin({
      userId: req.user!.userId,
      orgId: req.params.org,
      message: req.body?.message,
    })
    res.status(201).json({ request })
  }),
)

// owner 看本团队申请
router.get(
  "/orgs/:org/join-requests",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    res.json({ requests: await JoinService.listOrgRequests(req.tenant!.orgId!) })
  }),
)

// owner 批准
router.post(
  "/orgs/:org/join-requests/:id/approve",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    res.json(
      await JoinService.approve({
        requestId: req.params.id,
        orgId: req.tenant!.orgId!,
        ownerUserId: req.user!.userId,
      }),
    )
  }),
)

// owner 拒绝
router.post(
  "/orgs/:org/join-requests/:id/reject",
  requireAuth,
  orgGuard({ role: "owner" }),
  wrap(async (req, res) => {
    res.json(
      await JoinService.reject({
        requestId: req.params.id,
        orgId: req.tenant!.orgId!,
        ownerUserId: req.user!.userId,
      }),
    )
  }),
)

export default router
