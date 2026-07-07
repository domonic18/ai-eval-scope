/**
 * API Key 业务：签发（单一 Bearer token，明文仅返回一次）、列表、吊销、统计。
 *
 * 存储（§6.3 方案 A）：
 *  - tokenHash：sha256（鉴权查找）
 *  - tokenEncrypted：AES-256-GCM（executor 回传时解密得明文）
 *  - tokenPreview：明文前缀，供列表识别（不可还原）
 *  明文 token 永不落库、永不回显；签发响应仅含一次性的 plaintext token。
 */

import { ApiKey } from "@prisma/client"
import { ApiKeyRepository } from "../repositories/apiKey.repository"
import { ProjectRepository } from "../repositories/project.repository"
import { generateApiKey, encryptToken, hashToken } from "../infra/crypto"
import { AuditService } from "./audit.service"
import { PlatformError } from "../middleware/errorHandler"
import type { Tenant } from "../repositories/base.repository"

export interface ApiKeyIssueInput {
  name?: string
  expiresAt?: string | null
}
export interface IssuedKey {
  id: string
  token: string // 明文，仅本次返回
  tokenPreview: string
  name: string
  expiresAt: Date | null
  createdAt: Date
}
export interface SafeKey {
  id: string
  tokenPreview: string
  name: string
  expiresAt: Date | null
  lastUsedAt: Date | null
  lastIp: string | null
  callCount: string
  createdAt: Date
  revokedAt: Date | null
}

export interface ApiKeyService {
  list: (projectId: string) => Promise<SafeKey[]>
  issue: (projectId: string, input: ApiKeyIssueInput) => Promise<IssuedKey>
  revoke: (projectId: string, keyId: string) => Promise<SafeKey>
}

export function createApiKeyService(tenant: Tenant): ApiKeyService {
  const repo = new ApiKeyRepository(tenant)
  const projectRepo = new ProjectRepository(tenant)

  async function assertProjectInScope(projectId: string) {
    const p = await projectRepo.findByIdSafe(projectId)
    if (!p) {
      throw new PlatformError("project not found", { status: 404, code: "NOT_FOUND" })
    }
    return p
  }

  async function list(projectId: string): Promise<SafeKey[]> {
    await assertProjectInScope(projectId)
    const keys = await repo.listByProject(projectId)
    return keys.map(stripSecret)
  }

  async function issue(projectId: string, input: ApiKeyIssueInput): Promise<IssuedKey> {
    await assertProjectInScope(projectId)
    if (!input.name) {
      throw new PlatformError("name required", { status: 400, code: "SCHEMA_INVALID" })
    }

    const token = generateApiKey()
    const created = await repo.create({
      projectId,
      tokenHash: hashToken(token),
      tokenEncrypted: encryptToken(token),
      tokenPreview: token.slice(0, 12),
      name: input.name,
      expiresAt: input.expiresAt ? new Date(input.expiresAt) : null,
    })

    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "key.create",
      targetType: "api_key",
      targetId: created.id,
      metadata: { projectId, name: input.name, tokenPreview: token.slice(0, 12) },
    })

    return {
      id: created.id,
      token,
      tokenPreview: token.slice(0, 12),
      name: created.name,
      expiresAt: created.expiresAt,
      createdAt: created.createdAt,
    }
  }

  async function revoke(projectId: string, keyId: string): Promise<SafeKey> {
    await assertProjectInScope(projectId)
    const key = await repo.findById(keyId)
    if (!key || key.projectId !== projectId) {
      throw new PlatformError("key not found", { status: 404, code: "NOT_FOUND" })
    }
    if (key.revokedAt) {
      return stripSecret(key)
    }
    const revoked = await repo.revoke(keyId)
    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "key.revoke",
      targetType: "api_key",
      targetId: keyId,
      metadata: { projectId },
    })
    return stripSecret(revoked)
  }

  return { list, issue, revoke }
}

/** 去除一切可还原 token 的字段，供列表/吊销回显。 */
function stripSecret(key: ApiKey): SafeKey {
  return {
    id: key.id,
    tokenPreview: key.tokenPreview,
    name: key.name,
    expiresAt: key.expiresAt,
    lastUsedAt: key.lastUsedAt,
    lastIp: key.lastIp,
    callCount: key.callCount ? key.callCount.toString() : "0",
    createdAt: key.createdAt,
    revokedAt: key.revokedAt,
  }
}
