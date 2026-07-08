/**
 * 项目业务（CRUD / 归档）。tenant 由中间件注入；隔离由 repository 强制。
 */

import { Project } from "@prisma/client"
import { ProjectRepository } from "../repositories/project.repository"
import { AuditService } from "./audit.service"
import { getObjectStorage } from "../infra/objectStorage"
import { getLogger } from "../infra/logger"
import { PlatformError } from "../middleware/errorHandler"
import { slugify } from "../utils/slug"
import type { Tenant } from "../repositories/base.repository"

export interface ProjectCreateInput {
  name?: string
  slug?: string
  description?: string | null
  defaultRuleSet?: string | null
  defaultTaskSet?: string | null
  retentionDays?: number | null
}
export type ProjectPatch = Partial<
  Pick<
    Project,
    "name" | "description" | "defaultRuleSet" | "defaultTaskSet" | "retentionDays" | "isPublic"
  >
>

export interface ProjectService {
  list: (opts?: { includeArchived?: boolean }) => Promise<Project[]>
  get: (projectId: string) => Promise<Project>
  create: (input: ProjectCreateInput) => Promise<Project>
  update: (projectId: string, patch: ProjectPatch) => Promise<Project | null>
  setArchived: (projectId: string, archived: boolean) => Promise<Project | null>
  delete: (projectId: string) => Promise<void>
}

export function createProjectService(tenant: Tenant): ProjectService {
  const repo = new ProjectRepository(tenant)

  async function list(opts: { includeArchived?: boolean } = {}): Promise<Project[]> {
    return repo.listByOrg(opts)
  }

  async function get(projectId: string): Promise<Project> {
    const p = await repo.findByIdSafe(projectId)
    if (!p) throw new PlatformError("project not found", { status: 404, code: "NOT_FOUND" })
    return p
  }

  async function create(input: ProjectCreateInput): Promise<Project> {
    const finalSlug = slugify(input.slug || input.name)
    if (!finalSlug) {
      throw new PlatformError("invalid slug", { status: 400, code: "SCHEMA_INVALID" })
    }
    if (!input.name) {
      throw new PlatformError("name required", { status: 400, code: "SCHEMA_INVALID" })
    }
    try {
      const created = await repo.create({
        slug: finalSlug,
        name: input.name,
        description: input.description,
        defaultRuleSet: input.defaultRuleSet,
        defaultTaskSet: input.defaultTaskSet,
        retentionDays: input.retentionDays,
      })
      await AuditService.log({
        orgId: tenant.orgId,
        actorUserId: tenant.userId,
        action: "project.create",
        targetType: "project",
        targetId: created.id,
        metadata: { slug: finalSlug, name: input.name },
      })
      return created
    } catch (err) {
      if ((err as { code?: string }).code === "P2002") {
        throw new PlatformError("slug already used in this org", {
          status: 409,
          code: "SLUG_TAKEN",
        })
      }
      throw err
    }
  }

  async function update(projectId: string, patch: ProjectPatch): Promise<Project | null> {
    const allowed: ProjectPatch = {}
    for (const k of [
      "name",
      "description",
      "defaultRuleSet",
      "defaultTaskSet",
      "retentionDays",
      "isPublic",
    ] as const) {
      if (patch[k] !== undefined) (allowed as Record<string, unknown>)[k] = patch[k]
    }
    // 公开开关：仅 owner 可改（公开后项目运行/样本免登录可读，敏感）；且必须为布尔。
    if (allowed.isPublic !== undefined) {
      if (typeof allowed.isPublic !== "boolean") {
        throw new PlatformError("isPublic must be boolean", { status: 400, code: "SCHEMA_INVALID" })
      }
      if (tenant.role !== "owner") {
        throw new PlatformError("owner role required to toggle public", {
          status: 403,
          code: "FORBIDDEN",
        })
      }
    }
    const existing = await repo.findByIdSafe(projectId)
    if (!existing) throw new PlatformError("project not found", { status: 404, code: "NOT_FOUND" })
    const res = await repo.update(projectId, allowed)
    if (res.count === 0)
      throw new PlatformError("project not found", { status: 404, code: "NOT_FOUND" })
    // 审计：公开开关变更（docs/arch/12 §十）
    if (allowed.isPublic !== undefined && allowed.isPublic !== existing.isPublic) {
      await AuditService.log({
        orgId: tenant.orgId,
        actorUserId: tenant.userId,
        action: "project.public_toggle",
        targetType: "project",
        targetId: projectId,
        metadata: { isPublic: allowed.isPublic },
      })
    }
    return repo.findByIdSafe(projectId)
  }

  async function setArchived(projectId: string, archived: boolean): Promise<Project | null> {
    const existing = await repo.findByIdSafe(projectId)
    if (!existing) throw new PlatformError("project not found", { status: 404, code: "NOT_FOUND" })
    await repo.setArchived(projectId, archived)
    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: archived ? "project.archive" : "project.unarchive",
      targetType: "project",
      targetId: projectId,
    })
    return repo.findByIdSafe(projectId)
  }

  async function deleteProject(projectId: string): Promise<void> {
    const existing = await repo.findByIdSafe(projectId)
    if (!existing) throw new PlatformError("project not found", { status: 404, code: "NOT_FOUND" })
    const objectKeys = await repo.deleteProject(projectId)
    // 对象存储清理：best-effort，失败仅 warn（DB 已删，孤儿文件可后续清理）
    if (objectKeys.length) {
      try {
        await getObjectStorage().deleteObjects(objectKeys)
      } catch (err) {
        getLogger().warn(
          { projectId, count: objectKeys.length, error: (err as Error).message },
          "project_delete_objects_failed",
        )
      }
    }
    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "project.delete",
      targetType: "project",
      targetId: projectId,
      metadata: { slug: existing.slug, name: existing.name },
    })
  }

  return { list, get, create, update, setArchived, delete: deleteProject }
}
