/**
 * 团队加入业务：发现团队 / 申请加入 / owner 审批。
 * 纯团队中心模型：用户登录后无团队，通过「创建团队」或「申请加入」获得团队。
 */

import { getPrisma } from "../infra/prisma"
import { OrgRepository, UserRepository } from "../repositories/user.repository"
import { JoinRequestRepository } from "../repositories/join.repository"
import { AuditService } from "./audit.service"
import { PlatformError } from "../middleware/errorHandler"

const joinRepo = new JoinRequestRepository()
const orgRepo = new OrgRepository()
const userRepo = new UserRepository()

/** 列出所有团队（发现）+ 当前用户的成员/申请状态。 */
async function listTeams(userId: string) {
  const prisma = getPrisma()
  const orgs = await prisma.organization.findMany({ orderBy: { createdAt: "desc" } })
  const myMemberships = await userRepo.listMemberships(userId)
  const myRequests = await joinRepo.findByUser(userId)
  return orgs.map((o) => {
    const isMember = myMemberships.some((m) => m.orgId === o.id)
    const req = myRequests.find((r) => r.orgId === o.id)
    return {
      id: o.id,
      name: o.name,
      slug: o.slug,
      isMember,
      requestStatus: req?.status ?? null, // null | pending | approved | rejected
    }
  })
}

/** 我的加入申请（含团队名）。 */
async function listMyRequests(userId: string) {
  const rows = await joinRepo.findByUser(userId)
  return rows.map((r) => ({
    id: r.id,
    orgId: r.orgId,
    status: r.status,
    message: r.message,
    createdAt: r.createdAt,
    org: { name: r.org.name, slug: r.org.slug },
  }))
}

/** owner 看本团队的加入申请（含申请人信息）。 */
async function listOrgRequests(orgId: string) {
  const rows = await joinRepo.findByOrg(orgId)
  return rows.map((r) => ({
    id: r.id,
    status: r.status,
    message: r.message,
    createdAt: r.createdAt,
    user: { id: r.user.id, email: r.user.email, name: r.user.name },
  }))
}

/** 申请加入团队（须非成员、无既有申请记录）。 */
async function requestJoin(input: { userId: string; orgId: string; message?: string }) {
  const org = await orgRepo.findById(input.orgId)
  if (!org) {
    throw new PlatformError("team not found", { status: 404, code: "NOT_FOUND" })
  }
  if (await orgRepo.findMembership(input.orgId, input.userId)) {
    throw new PlatformError("already a member", { status: 409, code: "CONFLICT" })
  }
  if (await joinRepo.findActive(input.orgId, input.userId)) {
    throw new PlatformError("join request already exists", { status: 409, code: "CONFLICT" })
  }
  const req = await joinRepo.create({
    orgId: input.orgId,
    userId: input.userId,
    message: input.message ?? null,
  })
  await AuditService.log({
    actorUserId: input.userId,
    action: "join.request",
    targetType: "organization",
    targetId: input.orgId,
  })
  return { id: req.id, orgId: req.orgId, status: req.status, createdAt: req.createdAt }
}

/** owner 批准 → 建 membership(member) + 申请状态 approved。 */
async function approve(input: { requestId: string; orgId: string; ownerUserId: string }) {
  const req = await joinRepo.findById(input.requestId)
  if (!req || req.orgId !== input.orgId) {
    throw new PlatformError("request not found", { status: 404, code: "NOT_FOUND" })
  }
  if (req.status !== "pending") {
    throw new PlatformError("request already resolved", { status: 409, code: "CONFLICT" })
  }
  await orgRepo.addMember({ orgId: req.orgId, userId: req.userId, role: "member" })
  await joinRepo.updateStatus(req.id, "approved", input.ownerUserId)
  await AuditService.log({
    orgId: req.orgId,
    actorUserId: input.ownerUserId,
    action: "join.approve",
    targetType: "user",
    targetId: req.userId,
  })
  return { approved: true, userId: req.userId }
}

/** owner 拒绝 → 申请状态 rejected（不建 membership）。 */
async function reject(input: { requestId: string; orgId: string; ownerUserId: string }) {
  const req = await joinRepo.findById(input.requestId)
  if (!req || req.orgId !== input.orgId) {
    throw new PlatformError("request not found", { status: 404, code: "NOT_FOUND" })
  }
  if (req.status !== "pending") {
    throw new PlatformError("request already resolved", { status: 409, code: "CONFLICT" })
  }
  await joinRepo.updateStatus(req.id, "rejected", input.ownerUserId)
  await AuditService.log({
    orgId: req.orgId,
    actorUserId: input.ownerUserId,
    action: "join.reject",
    targetType: "user",
    targetId: req.userId,
  })
  return { rejected: true }
}

export const JoinService = {
  listTeams,
  listMyRequests,
  listOrgRequests,
  requestJoin,
  approve,
  reject,
}
