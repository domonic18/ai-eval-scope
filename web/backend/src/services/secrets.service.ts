/**
 * 平台 Secrets 服务（org 级通用 KV，GitHub Secrets 式，arch/16 §2.4）。
 *
 * - 写入：encryptToken（AES-256-GCM，PLATFORM_KEY_ENCRYPTION_KEY）后存 valueEncrypted；
 * - 管理面读取：只回 name + 时间，**值写后不可读**（列表永不回显）；
 * - 执行面拉取：executor 经 API Key 解析 org 后全量解密返回（审计打点不含值）。
 */

import type { PrismaClient } from "@prisma/client"
import { decryptToken, encryptToken } from "../infra/crypto"
import { getLogger } from "../infra/logger"
import { PlatformError } from "../middleware/errorHandler"
import { getPrisma } from "../infra/prisma"

/** Secret 名约束：env 变量风格（大写字母/数字/下划线），与 executor 注入 env 对齐。 */
const NAME_PATTERN = /^[A-Z][A-Z0-9_]*$/

export interface SecretView {
  name: string
  createdAt: string
  updatedAt: string
}

export function assertSecretName(name: string): void {
  if (!NAME_PATTERN.test(name)) {
    throw new PlatformError("name 需为大写字母/数字/下划线（env 变量风格，如 SASAN__USERNAME）", {
      status: 400,
      code: "VALIDATION",
    })
  }
}

export function createSecretsService(orgId: string, prisma: PrismaClient = getPrisma()) {
  /** 列表（不含值——写后不可读）。 */
  async function list(): Promise<SecretView[]> {
    const rows = await prisma.secret.findMany({ where: { orgId }, orderBy: { name: "asc" } })
    return rows.map((r) => ({
      name: r.name,
      createdAt: r.createdAt.toISOString(),
      updatedAt: r.updatedAt.toISOString(),
    }))
  }

  /** 新增/覆盖（值加密存储；不回显）。 */
  async function upsert(name: string, value: string, userId: string): Promise<SecretView> {
    assertSecretName(name)
    if (!value) throw new PlatformError("value 必填", { status: 400, code: "VALIDATION" })
    const row = await prisma.secret.upsert({
      where: { orgId_name: { orgId, name } },
      update: { valueEncrypted: encryptToken(value), createdBy: userId },
      create: { orgId, name, valueEncrypted: encryptToken(value), createdBy: userId },
    })
    getLogger().info({ orgId, name }, "[secret] upsert")
    return {
      name: row.name,
      createdAt: row.createdAt.toISOString(),
      updatedAt: row.updatedAt.toISOString(),
    }
  }

  async function remove(name: string): Promise<void> {
    const row = await prisma.secret.findUnique({ where: { orgId_name: { orgId, name } } })
    if (!row) throw new PlatformError("secret not found", { status: 404, code: "NOT_FOUND" })
    await prisma.secret.delete({ where: { id: row.id } })
    getLogger().info({ orgId, name }, "[secret] delete")
  }

  /** 执行面拉取：全量解密 KV（仅 /api/public/secrets 调用；审计不含值）。 */
  async function resolveForExecutor(actor: string): Promise<Record<string, string>> {
    const rows = await prisma.secret.findMany({ where: { orgId }, orderBy: { name: "asc" } })
    const out: Record<string, string> = {}
    for (const row of rows) {
      try {
        out[row.name] = decryptToken(row.valueEncrypted)
      } catch {
        getLogger().warn({ orgId, name: row.name }, "[secret] decrypt_failed_skip")
      }
    }
    getLogger().info({ orgId, count: rows.length, actor }, "[secret] executor pull")
    return out
  }

  return { list, upsert, remove, resolveForExecutor }
}
