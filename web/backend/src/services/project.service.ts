/**
 * 项目业务（CRUD / 归档）。tenant 由中间件注入；隔离由 repository 强制。
 */

import { Project } from "@prisma/client"
import { ProjectRepository } from "../repositories/project.repository"
import { AuditService } from "./audit.service"
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
  Pick<Project, "name" | "description" | "defaultRuleSet" | "defaultTaskSet" | "retentionDays">
>

export interface ProjectService {
  list: (opts?: { includeArchived?: boolean }) => Promise<Project[]>
  get: (projectId: string) => Promise<Project>
  create: (input: ProjectCreateInput) => Promise<Project>
  update: (projectId: string, patch: ProjectPatch) => Promise<Project | null>
  setArchived: (projectId: string, archived: boolean) => Promise<Project | null>
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
    ] as const) {
      if (patch[k] !== undefined) (allowed as Record<string, unknown>)[k] = patch[k]
    }
    const existing = await repo.findByIdSafe(projectId)
    if (!existing) throw new PlatformError("project not found", { status: 404, code: "NOT_FOUND" })
    const res = await repo.update(projectId, allowed)
    if (res.count === 0)
      throw new PlatformError("project not found", { status: 404, code: "NOT_FOUND" })
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

  return { list, get, create, update, setArchived }
}
