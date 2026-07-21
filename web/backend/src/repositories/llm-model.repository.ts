/**
 * LLM 模型配置仓库（docs/arch/15）。单表多模型；api_key 加密存储，回显仅脱敏。
 * is_default 全局唯一（partial unique index），原子切换。
 */
import type { LlmModel, Prisma } from "@prisma/client"
import { getPrisma } from "../infra/prisma"
import { decryptToken, encryptToken, maskToken } from "../infra/crypto"
import { PlatformError } from "../middleware/errorHandler"

export type LlmProtocol = "openai" | "anthropic"

/** 对外回显形状（api_key 仅脱敏，明文永不下发）。 */
export interface LlmModelVO {
  id: string
  name: string
  provider: string
  baseUrl: string | null
  apiKeyMasked: string
  modelName: string
  isActive: boolean
  isDefault: boolean
  extra: Record<string, unknown> | null
  lastTestedAt: string | null
  lastTestStatus: string | null
  lastTestError: string | null
  createdAt: string
  updatedAt: string
}

export interface LlmModelInput {
  name: string
  provider: string
  baseUrl?: string | null
  apiKey?: string // 明文；创建必填，更新留空=不改
  modelName: string
  isActive?: boolean
  isDefault?: boolean
  extra?: Record<string, unknown> | null
}

function toVO(m: LlmModel): LlmModelVO {
  let apiKeyMasked = "••••"
  try {
    apiKeyMasked = maskToken(decryptToken(m.apiKeyEncrypted))
  } catch {
    /* 密文损坏时仅显示占位 */
  }
  return {
    id: m.id,
    name: m.name,
    provider: m.provider,
    baseUrl: m.baseUrl,
    apiKeyMasked,
    modelName: m.modelName,
    isActive: m.isActive,
    isDefault: m.isDefault,
    extra: (m.extra as Record<string, unknown> | null) ?? null,
    lastTestedAt: m.lastTestedAt ? m.lastTestedAt.toISOString() : null,
    lastTestStatus: m.lastTestStatus,
    lastTestError: m.lastTestError,
    createdAt: m.createdAt.toISOString(),
    updatedAt: m.updatedAt.toISOString(),
  }
}

class LlmModelRepository {
  private prisma = getPrisma()

  /** 列表：默认项置顶，其次按创建时间倒序。 */
  async list(): Promise<LlmModelVO[]> {
    const rows = await this.prisma.llmModel.findMany({
      orderBy: [{ isDefault: "desc" }, { createdAt: "desc" }],
    })
    return rows.map(toVO)
  }

  async getRaw(id: string): Promise<LlmModel | null> {
    return this.prisma.llmModel.findUnique({ where: { id } })
  }

  /** 取默认模型原始行（含密文 key）；无默认则取首个 active。 */
  async getDefaultRaw(): Promise<LlmModel | null> {
    const def = await this.prisma.llmModel.findFirst({
      where: { isDefault: true, isActive: true },
    })
    if (def) return def
    return this.prisma.llmModel.findFirst({ where: { isActive: true }, orderBy: { createdAt: "desc" } })
  }

  async create(input: LlmModelInput): Promise<LlmModelVO> {
    if (!input.apiKey) throw new PlatformError("api_key 必填", { status: 400, code: "VALIDATION_ERROR" })
    if (!["openai", "anthropic"].includes(input.provider)) {
      throw new PlatformError("provider 必须为 openai 或 anthropic", { status: 400, code: "VALIDATION_ERROR" })
    }
    const apiKey = input.apiKey
    return this.prisma.$transaction(async (tx) => {
      if (input.isDefault) await tx.llmModel.updateMany({ where: { isDefault: true }, data: { isDefault: false } })
      const row = await tx.llmModel.create({
        data: {
          name: input.name,
          provider: input.provider,
          baseUrl: input.baseUrl ?? null,
          apiKeyEncrypted: encryptToken(apiKey),
          modelName: input.modelName,
          isActive: input.isActive ?? true,
          isDefault: input.isDefault ?? false,
          extra: (input.extra ?? null) as Prisma.InputJsonValue,
        },
      })
      return toVO(row)
    })
  }

  async update(id: string, input: Partial<LlmModelInput>): Promise<LlmModelVO> {
    if (input.provider && !["openai", "anthropic"].includes(input.provider)) {
      throw new PlatformError("provider 必须为 openai 或 anthropic", { status: 400, code: "VALIDATION_ERROR" })
    }
    const existing = await this.getRaw(id)
    if (!existing) throw new PlatformError("llm model not found", { status: 404, code: "NOT_FOUND" })
    return this.prisma.$transaction(async (tx) => {
      if (input.isDefault) await tx.llmModel.updateMany({ where: { isDefault: true }, data: { isDefault: false } })
      const data: Prisma.LlmModelUpdateInput = {}
      if (input.name !== undefined) data.name = input.name
      if (input.provider !== undefined) data.provider = input.provider
      if (input.baseUrl !== undefined) data.baseUrl = input.baseUrl
      if (input.modelName !== undefined) data.modelName = input.modelName
      if (input.isActive !== undefined) data.isActive = input.isActive
      if (input.isDefault !== undefined) {
        data.isDefault = input.isDefault
        if (input.isDefault) data.isActive = true
      }
      if (input.extra !== undefined) data.extra = input.extra as Prisma.InputJsonValue
      if (input.apiKey) data.apiKeyEncrypted = encryptToken(input.apiKey)
      const row = await tx.llmModel.update({ where: { id }, data })
      return toVO(row)
    })
  }

  /** 删除；若删的是默认项，自动改派首个 active 为默认。缺失 ID → 404。 */
  async remove(id: string): Promise<void> {
    const existing = await this.getRaw(id)
    if (!existing) throw new PlatformError("llm model not found", { status: 404, code: "NOT_FOUND" })
    await this.prisma.$transaction(async (tx) => {
      await tx.llmModel.delete({ where: { id } })
      if (existing.isDefault) {
        const next = await tx.llmModel.findFirst({ where: { isActive: true }, orderBy: { createdAt: "desc" } })
        if (next) await tx.llmModel.update({ where: { id: next.id }, data: { isDefault: true } })
      }
    })
  }

  async setDefault(id: string): Promise<LlmModelVO> {
    return this.prisma.$transaction(async (tx) => {
      const target = await tx.llmModel.findUnique({ where: { id } })
      if (!target) throw new PlatformError("llm model not found", { status: 404, code: "NOT_FOUND" })
      await tx.llmModel.updateMany({ where: { isDefault: true }, data: { isDefault: false } })
      const row = await tx.llmModel.update({ where: { id }, data: { isDefault: true, isActive: true } })
      return toVO(row)
    })
  }

  /** 写回测试结果。 */
  async recordTest(id: string, status: "success" | "failed", error: string | null): Promise<void> {
    await this.prisma.llmModel.update({
      where: { id },
      data: { lastTestedAt: new Date(), lastTestStatus: status, lastTestError: error },
    })
  }
}

export const llmModelRepository = new LlmModelRepository()
