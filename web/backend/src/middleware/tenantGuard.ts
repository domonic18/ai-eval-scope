/**
 * 租户上下文与越权拦截中间件（§6.4 隔离实现）。
 *
 * - orgGuard：解析 :org（org id）→ 校验 req.user 是该组织成员（及角色）→ 注入 req.tenant。
 * - projectGuard：解析 :id（project id）→ 自举项目归属 → 校验用户属其组织 → 注入 req.tenant（含 projectId）。
 *
 * 越权一律 404（不泄露存在性）。
 */

import type { RequestHandler } from "express"
import { OrgRepository } from "../repositories/user.repository"
import { ProjectRepository } from "../repositories/project.repository"
import { getPrisma } from "../infra/prisma"
import { PlatformError } from "./errorHandler"

const orgRepo = new OrgRepository()
const projectRepoBootstrap = new ProjectRepository({})
const prisma = getPrisma()

export interface GuardOpts {
  param?: string
  role?: "owner" | "member"
}

/** 组织级守卫。 */
export function orgGuard(opts: GuardOpts = {}): RequestHandler {
  const param = opts.param || "org"
  const requiredRole = opts.role || "member"
  return async (req, _res, next) => {
    try {
      const orgId: string | undefined = req.params[param]
      if (!req.user) {
        return next(new PlatformError("auth required", { status: 401, code: "AUTH_INVALID" }))
      }
      const membership = await orgRepo.findMembership(orgId!, req.user.userId)
      if (!membership) {
        return next(new PlatformError("not found", { status: 404, code: "NOT_FOUND" }))
      }
      if (requiredRole === "owner" && membership.role !== "owner") {
        return next(new PlatformError("owner role required", { status: 403, code: "FORBIDDEN" }))
      }
      req.tenant = {
        kind: "user",
        userId: req.user.userId,
        orgId,
        role: membership.role,
      }
      next()
    } catch (err) {
      next(err)
    }
  }
}

/** 项目级守卫（路由参数为 :id）。 */
export function projectGuard(opts: GuardOpts = {}): RequestHandler {
  const param = opts.param || "id"
  const requiredRole = opts.role || "member"
  return async (req, _res, next) => {
    try {
      const projectId: string | undefined = req.params[param]
      if (!req.user) {
        return next(new PlatformError("auth required", { status: 401, code: "AUTH_INVALID" }))
      }
      const project = await projectRepoBootstrap.findByIdAny(projectId!)
      if (!project || project.archivedAt) {
        return next(new PlatformError("not found", { status: 404, code: "NOT_FOUND" }))
      }
      const membership = await orgRepo.findMembership(project.orgId, req.user.userId)
      if (!membership) {
        return next(new PlatformError("not found", { status: 404, code: "NOT_FOUND" }))
      }
      if (requiredRole === "owner" && membership.role !== "owner") {
        return next(new PlatformError("owner role required", { status: 403, code: "FORBIDDEN" }))
      }
      req.tenant = {
        kind: "user",
        userId: req.user.userId,
        orgId: project.orgId,
        projectId,
        role: membership.role,
      }
      next()
    } catch (err) {
      next(err)
    }
  }
}

/**
 * 运行级守卫（路由参数 :id = run id）→ 解析 run→project→org→成员关系。
 * 注入 req.tenant（含 projectId = run 所属项目）。
 */
export function runGuard(opts: GuardOpts = {}): RequestHandler {
  const param = opts.param || "id"
  const requiredRole = opts.role || "member"
  return async (req, _res, next) => {
    try {
      const runId: string | undefined = req.params[param]
      if (!req.user) {
        return next(new PlatformError("auth required", { status: 401, code: "AUTH_INVALID" }))
      }
      const run = await prisma.run.findUnique({
        where: { id: runId! },
        select: { id: true, projectId: true },
      })
      if (!run) {
        return next(new PlatformError("not found", { status: 404, code: "NOT_FOUND" }))
      }
      const project = await projectRepoBootstrap.findByIdAny(run.projectId)
      if (!project) {
        return next(new PlatformError("not found", { status: 404, code: "NOT_FOUND" }))
      }
      const membership = await orgRepo.findMembership(project.orgId, req.user.userId)
      if (!membership) {
        return next(new PlatformError("not found", { status: 404, code: "NOT_FOUND" }))
      }
      if (requiredRole === "owner" && membership.role !== "owner") {
        return next(new PlatformError("owner role required", { status: 403, code: "FORBIDDEN" }))
      }
      req.tenant = {
        kind: "user",
        userId: req.user.userId,
        orgId: project.orgId,
        projectId: run.projectId,
        role: membership.role,
      }
      next()
    } catch (err) {
      next(err)
    }
  }
}

/**
 * 制品级守卫（路由参数 :id = artifact id）→ 解析 artifact→project→org→成员关系。
 * 用于制品下载签发前的归属校验。
 */
export function artifactGuard(): RequestHandler {
  return async (req, _res, next) => {
    try {
      const artifactId: string | undefined = req.params.id
      if (!req.user) {
        return next(new PlatformError("auth required", { status: 401, code: "AUTH_INVALID" }))
      }
      const art = await prisma.artifact.findUnique({
        where: { id: artifactId! },
        select: { id: true, project: { select: { id: true, orgId: true } } },
      })
      if (!art) {
        return next(new PlatformError("not found", { status: 404, code: "NOT_FOUND" }))
      }
      const membership = await orgRepo.findMembership(art.project.orgId, req.user.userId)
      if (!membership) {
        return next(new PlatformError("not found", { status: 404, code: "NOT_FOUND" }))
      }
      req.tenant = {
        kind: "user",
        userId: req.user.userId,
        orgId: art.project.orgId,
        projectId: art.project.id,
        role: membership.role,
      }
      next()
    } catch (err) {
      next(err)
    }
  }
}
