/**
 * API Key 业务：签发（secret 明文仅返回一次）、列表、吊销、统计。
 *
 * 存储（§6.3 方案 A）：
 *  - secretHash：sha256（审计/不回显）
 *  - secretEncrypted：AES-256-GCM（HMAC 验签时解密得明文）
 *  明文永不落库、永不回显；签发响应仅含一次性的 plaintext secret。
 */

import { ApiKey } from "@prisma/client";
import { ApiKeyRepository } from "../repositories/apiKey.repository";
import { ProjectRepository } from "../repositories/project.repository";
import {
  generateApiKeyPair,
  encryptSecret,
  hashSecret,
} from "../infra/crypto";
import { AuditService } from "./audit.service";
import { PlatformError } from "../middleware/errorHandler";
import type { Tenant } from "../repositories/base.repository";

export interface ApiKeyIssueInput {
  name?: string;
  expiresAt?: string | null;
}
export interface IssuedKey {
  id: string;
  publicKey: string;
  secretKey: string; // 明文，仅本次返回
  name: string;
  expiresAt: Date | null;
  createdAt: Date;
}
export interface SafeKey {
  id: string;
  publicKey: string;
  name: string;
  expiresAt: Date | null;
  lastUsedAt: Date | null;
  lastIp: string | null;
  callCount: string;
  createdAt: Date;
  revokedAt: Date | null;
}

export interface ApiKeyService {
  list: (projectId: string) => Promise<SafeKey[]>;
  issue: (projectId: string, input: ApiKeyIssueInput) => Promise<IssuedKey>;
  revoke: (projectId: string, keyId: string) => Promise<SafeKey>;
}

export function createApiKeyService(tenant: Tenant): ApiKeyService {
  const repo = new ApiKeyRepository(tenant);
  const projectRepo = new ProjectRepository(tenant);

  async function assertProjectInScope(projectId: string) {
    const p = await projectRepo.findByIdSafe(projectId);
    if (!p) {
      throw new PlatformError("project not found", { status: 404, code: "NOT_FOUND" });
    }
    return p;
  }

  async function list(projectId: string): Promise<SafeKey[]> {
    await assertProjectInScope(projectId);
    const keys = await repo.listByProject(projectId);
    return keys.map(stripSecret);
  }

  async function issue(projectId: string, input: ApiKeyIssueInput): Promise<IssuedKey> {
    await assertProjectInScope(projectId);
    if (!input.name) {
      throw new PlatformError("name required", { status: 400, code: "SCHEMA_INVALID" });
    }

    const { publicKey, secretKey } = generateApiKeyPair();
    const created = await repo.create({
      projectId,
      publicKey,
      secretHash: hashSecret(secretKey),
      secretEncrypted: encryptSecret(secretKey),
      name: input.name,
      expiresAt: input.expiresAt ? new Date(input.expiresAt) : null,
    });

    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "key.create",
      targetType: "api_key",
      targetId: created.id,
      metadata: { projectId, name: input.name, publicKey },
    });

    return {
      id: created.id,
      publicKey,
      secretKey,
      name: created.name,
      expiresAt: created.expiresAt,
      createdAt: created.createdAt,
    };
  }

  async function revoke(projectId: string, keyId: string): Promise<SafeKey> {
    await assertProjectInScope(projectId);
    const key = await repo.findById(keyId);
    if (!key || key.projectId !== projectId) {
      throw new PlatformError("key not found", { status: 404, code: "NOT_FOUND" });
    }
    if (key.revokedAt) {
      return stripSecret(key);
    }
    const revoked = await repo.revoke(keyId);
    await AuditService.log({
      orgId: tenant.orgId,
      actorUserId: tenant.userId,
      action: "key.revoke",
      targetType: "api_key",
      targetId: keyId,
      metadata: { projectId },
    });
    return stripSecret(revoked);
  }

  return { list, issue, revoke };
}

/** 去除一切可还原 secret 的字段，供列表/吊销回显。 */
function stripSecret(key: ApiKey): SafeKey {
  return {
    id: key.id,
    publicKey: key.publicKey,
    name: key.name,
    expiresAt: key.expiresAt,
    lastUsedAt: key.lastUsedAt,
    lastIp: key.lastIp,
    callCount: key.callCount ? key.callCount.toString() : "0",
    createdAt: key.createdAt,
    revokedAt: key.revokedAt,
  };
}
