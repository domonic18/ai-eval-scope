/**
 * 场景包配置资产读取（Phase 3，对齐 13 §11.2）。
 *
 * 替代构建期静态 rule-sets.json：从 scenarios / *_assets 表动态组装 catalog。
 * 资产按 (scenarioId, assetId, version) 唯一；catalog 默认返回每个 assetId 的最新版本
 * （labels 含 production 优先，否则最高版本）。
 */

import { createHash } from "crypto"
import { Prisma, type PrismaClient } from "@prisma/client"
import { getPrisma } from "../infra/prisma"
import { PlatformError } from "../middleware/errorHandler"
import { MUTUALLY_EXCLUSIVE_LABELS, pickLatestPerAsset } from "../utils/versioning"

function hashContent(content: unknown): string {
  return "sha256:" + createHash("sha256").update(JSON.stringify(content)).digest("hex")
}

/** 同版本号重发：版本不可变（S1-2），拒绝并要求升版本号。 */
function versionConflict(assetId: string, version: string): PlatformError {
  return new PlatformError(`资产版本已存在（不可变）：${assetId}@${version}，请升版本号`, {
    status: 409,
    code: "CONFLICT",
  })
}

/** 确保场景行存在（资产发布前 upsert）。 */
async function prismaEnsureScenario(prisma: PrismaClient, scenarioId: string): Promise<void> {
  await prisma.scenario.upsert({
    where: { id: scenarioId },
    update: {},
    create: { id: scenarioId, name: scenarioId },
  })
}

export interface CatalogEntry {
  asset_id: string
  version: string
  labels: string[]
  name: string | null
  description: string | null
}

export interface ScenarioCatalog {
  scenario: { id: string; name: string; description: string | null }
  rule_sets: CatalogEntry[]
  prompts: CatalogEntry[]
  datasets: Array<CatalogEntry & { role: string; backend_type: string }>
}

export class ScenarioRepository {
  constructor(private readonly prisma: PrismaClient = getPrisma()) {}

  async listScenarios() {
    return this.prisma.scenario.findMany({ orderBy: { id: "asc" } })
  }

  /** 发布场景默认配置（指标定义 + 聚合策略）版本（版本不可变；assetId 固定 "default"）。 */
  async publishDefaultsAsset(
    scenarioId: string,
    input: {
      version: string
      labels?: string[]
      content: Record<string, unknown> // { metric_definitions?, aggregation_policy? }
      createdBy: string
    },
  ): Promise<{ assetId: string; version: string }> {
    const assetId = "default"
    const contentHash = hashContent(input.content)
    await prismaEnsureScenario(this.prisma, scenarioId)
    const existing = await this.prisma.defaultsAsset.findUnique({
      where: { scenarioId_assetId_version: { scenarioId, assetId, version: input.version } },
      select: { id: true, contentHash: true },
    })
    // 幂等：同版本同内容重发（importAssetsToDb 重导）直接返回；同版本不同内容才冲突
    if (existing) {
      if (existing.contentHash === contentHash) return { assetId, version: input.version }
      throw versionConflict(assetId, input.version)
    }
    await this.prisma.defaultsAsset.create({
      data: {
        scenarioId,
        assetId,
        version: input.version,
        labels: input.labels ?? [],
        content: input.content as never,
        contentHash,
        createdBy: input.createdBy,
      },
    })
    return { assetId, version: input.version }
  }

  /** 列出场景默认配置的全部历史版本（VersionTimeline 用）。 */
  async listDefaultsVersions(
    scenarioId: string,
  ): Promise<Array<{ version: string; labels: string[]; contentHash: string; createdAt: Date }>> {
    return this.prisma.defaultsAsset.findMany({
      where: { scenarioId, assetId: "default" },
      select: { version: true, labels: true, contentHash: true, createdAt: true },
      orderBy: { createdAt: "desc" },
    })
  }

  /** 读取场景默认配置最新（或指定）版本的 content（GET /defaults 用）。 */
  async getDefaultsContent(
    scenarioId: string,
    version?: string,
  ): Promise<{ version: string; labels: string[]; content: Record<string, unknown> } | null> {
    const rows = await this.prisma.defaultsAsset.findMany({
      where: { scenarioId, assetId: "default" },
    })
    if (!rows.length) return null
    const chosen = version ? rows.find((r) => r.version === version) : pickLatestPerAsset(rows)[0]
    if (!chosen) return null
    return {
      version: chosen.version,
      labels: chosen.labels,
      content: chosen.content as Record<string, unknown>,
    }
  }

  /** 标签晋升：覆盖默认配置某版本的 labels（latest/production/staging 互斥）。 */
  async setDefaultsLabels(scenarioId: string, version: string, labels: string[]): Promise<void> {
    const exclusive = labels.filter((l) => (MUTUALLY_EXCLUSIVE_LABELS as readonly string[]).includes(l))
    await this.prisma.$transaction(async (tx) => {
      if (exclusive.length) {
        const others = await tx.defaultsAsset.findMany({
          where: { scenarioId, assetId: "default", NOT: { version } },
          select: { id: true, labels: true },
        })
        for (const o of others) {
          if (!o.labels.some((l) => exclusive.includes(l))) continue
          await tx.defaultsAsset.update({
            where: { id: o.id },
            data: { labels: o.labels.filter((l) => !exclusive.includes(l)) },
          })
        }
      }
      await tx.defaultsAsset.updateMany({
        where: { scenarioId, assetId: "default", version },
        data: { labels },
      })
    })
  }

  /** 发布/更新一个场景包版本（幂等 upsert；场景不存在则创建）。 */
  async publishPackage(
    scenarioId: string,
    input: {
      name?: string
      description?: string
      assetId: string
      version: string
      labels?: string[]
      content: Record<string, unknown>
      createdBy: string
    },
  ): Promise<{ packageId: string; scenarioId: string }> {
    return this.prisma.$transaction(async (tx) => {
      await tx.scenario.upsert({
        where: { id: scenarioId },
        update: { name: input.name ?? undefined, description: input.description ?? undefined },
        create: {
          id: scenarioId,
          name: input.name || scenarioId,
          description: input.description ?? null,
        },
      })
      const contentHash = hashContent(input.content)
      // S1-2 版本不可变：同 (scenario, asset, version) 重发拒绝（409），不再 upsert 覆盖。
      const existing = await tx.scenarioPackage.findUnique({
        where: {
          scenarioId_assetId_version: { scenarioId, assetId: input.assetId, version: input.version },
        },
        select: { id: true },
      })
      if (existing) throw versionConflict(input.assetId, input.version)
      const created = await tx.scenarioPackage.create({
        data: {
          scenarioId,
          assetId: input.assetId,
          version: input.version,
          labels: input.labels ?? [],
          content: input.content as never,
          contentHash,
          createdBy: input.createdBy,
        },
        select: { id: true },
      })
      return { packageId: created.id, scenarioId }
    })
  }

  /**
   * 读取场景包内容（S2-A，executor/evaluator 运行时拉取用；公开读）。
   * 解析优先级：显式 version > label（如 production）> 最新（rank+semver）。
   * content 由发布方按 `{ manifest, files: { 相对路径: 内容 } }` 结构存入，原样下发，
   * evaluator 侧 PackageStore.install 可直接消费（ADR-01）。
   */
  async getPackageContent(
    scenarioId: string,
    assetId: string,
    version?: string,
    label?: string,
  ): Promise<{ version: string; labels: string[]; content: Record<string, unknown> } | null> {
    const rows = await this.prisma.scenarioPackage.findMany({ where: { scenarioId, assetId } })
    if (!rows.length) return null
    let chosen: (typeof rows)[number] | undefined
    if (version) {
      chosen = rows.find((r) => r.version === version)
    } else if (label) {
      chosen = pickLatestPerAsset(rows.filter((r) => r.labels.includes(label)))[0]
    } else {
      chosen = pickLatestPerAsset(rows)[0]
    }
    if (!chosen) return null
    return {
      version: chosen.version,
      labels: chosen.labels,
      content: chosen.content as Record<string, unknown>,
    }
  }

  /** 发布一个规则集资产版本（版本不可变；同版本号重发返回 409）。 */
  async publishRuleSetAsset(
    scenarioId: string,
    input: {
      assetId: string
      version: string
      labels?: string[]
      content: Record<string, unknown>
      createdBy: string
      packageId?: string
    },
  ): Promise<{ assetId: string; version: string }> {
    const contentHash = hashContent(input.content)
    await prismaEnsureScenario(this.prisma, scenarioId)
    const existing = await this.prisma.ruleSetAsset.findUnique({
      where: { scenarioId_assetId_version: { scenarioId, assetId: input.assetId, version: input.version } },
      select: { id: true },
    })
    if (existing) throw versionConflict(input.assetId, input.version)
    await this.prisma.ruleSetAsset.create({
      data: {
        scenarioId,
        packageId: input.packageId ?? null,
        assetId: input.assetId,
        version: input.version,
        labels: input.labels ?? [],
        content: input.content as never,
        contentHash,
        createdBy: input.createdBy,
      },
    })
    return { assetId: input.assetId, version: input.version }
  }

  /** 发布一个提示词资产版本（版本不可变；同版本号重发返回 409）。 */
  async publishPromptAsset(
    scenarioId: string,
    input: {
      assetId: string
      namespace?: string
      version: string
      labels?: string[]
      content: Record<string, unknown>
      createdBy: string
      packageId?: string
    },
  ): Promise<{ assetId: string; version: string }> {
    const namespace = input.namespace ?? scenarioId
    const contentHash = hashContent(input.content)
    await prismaEnsureScenario(this.prisma, scenarioId)
    const existing = await this.prisma.promptTemplateAsset.findUnique({
      where: {
        scenarioId_namespace_assetId_version: {
          scenarioId,
          namespace,
          assetId: input.assetId,
          version: input.version,
        },
      },
      select: { id: true },
    })
    if (existing) throw versionConflict(input.assetId, input.version)
    await this.prisma.promptTemplateAsset.create({
      data: {
        scenarioId,
        packageId: input.packageId ?? null,
        assetId: input.assetId,
        namespace,
        version: input.version,
        labels: input.labels ?? [],
        content: input.content as never,
        contentHash,
        createdBy: input.createdBy,
      },
    })
    return { assetId: input.assetId, version: input.version }
  }

  /** 发布一个数据集资产版本（版本不可变；同版本号重发返回 409）。 */
  async publishDatasetAsset(
    scenarioId: string,
    input: {
      assetId: string
      role: string // test | reference
      version: string
      labels?: string[]
      backendType: string
      backendConfig: Record<string, unknown>
      content: Record<string, unknown>
      createdBy: string
      packageId?: string
    },
  ): Promise<{ assetId: string; version: string }> {
    const contentHash = hashContent(input.content)
    await prismaEnsureScenario(this.prisma, scenarioId)
    const existing = await this.prisma.datasetAsset.findUnique({
      where: { scenarioId_assetId_version: { scenarioId, assetId: input.assetId, version: input.version } },
      select: { id: true },
    })
    if (existing) throw versionConflict(input.assetId, input.version)
    await this.prisma.datasetAsset.create({
      data: {
        scenarioId,
        packageId: input.packageId ?? null,
        assetId: input.assetId,
        role: input.role,
        version: input.version,
        labels: input.labels ?? [],
        backendType: input.backendType,
        backendConfig: input.backendConfig as never,
        content: input.content as never,
        contentHash,
        createdBy: input.createdBy,
      },
    })
    return { assetId: input.assetId, version: input.version }
  }

  /** 列出某资产的全部历史版本（VersionTimeline 用）。 */
  async listAssetVersions(
    scenarioId: string,
    kind: "rule-sets" | "prompts" | "datasets",
    assetId: string,
  ): Promise<Array<{ version: string; labels: string[]; contentHash: string; createdAt: Date }>> {
    const select = { version: true, labels: true, contentHash: true, createdAt: true }
    if (kind === "rule-sets") {
      return this.prisma.ruleSetAsset.findMany({ where: { scenarioId, assetId }, select, orderBy: { createdAt: "desc" } })
    }
    if (kind === "datasets") {
      return this.prisma.datasetAsset.findMany({ where: { scenarioId, assetId }, select, orderBy: { createdAt: "desc" } })
    }
    return this.prisma.promptTemplateAsset.findMany({ where: { scenarioId, assetId }, select, orderBy: { createdAt: "desc" } })
  }

  /** 获取某资产指定版本的完整 content（评测规则浏览器/编辑器 diff 用）。 */
  async getAssetContent(
    scenarioId: string,
    kind: "rule-sets" | "prompts" | "datasets",
    assetId: string,
    version?: string,
  ): Promise<Record<string, unknown> | null> {
    const rows =
      kind === "rule-sets"
        ? await this.prisma.ruleSetAsset.findMany({ where: { scenarioId, assetId } })
        : kind === "datasets"
          ? await this.prisma.datasetAsset.findMany({ where: { scenarioId, assetId } })
          : await this.prisma.promptTemplateAsset.findMany({ where: { scenarioId, assetId } })
    if (!rows.length) return null
    if (version) {
      const exact = rows.find((r) => r.version === version)
      return (exact?.content as Record<string, unknown>) ?? null
    }
    const latest = pickLatestPerAsset(rows)[0]
    return latest.content as Record<string, unknown>
  }

  /**
   * 标签晋升：覆盖某资产版本的 labels（S1-4 互斥）。
   * production / staging / latest 为互斥标签——赋予某版本时，从同资产其它版本摘除同名标签，
   * 保证每个互斥标签在资产内全局唯一。其余自定义标签不受影响。
   */
  async setAssetLabels(
    scenarioId: string,
    kind: "rule-sets" | "prompts" | "datasets",
    assetId: string,
    version: string,
    labels: string[],
  ): Promise<void> {
    const exclusive = labels.filter((l) => (MUTUALLY_EXCLUSIVE_LABELS as readonly string[]).includes(l))
    await this.prisma.$transaction(async (tx) => {
      if (exclusive.length) {
        await this._stripLabelsFromOthers(tx, kind, scenarioId, assetId, version, exclusive)
      }
      const filter = { scenarioId, assetId, version }
      if (kind === "rule-sets") await tx.ruleSetAsset.updateMany({ where: filter, data: { labels } })
      else if (kind === "datasets") await tx.datasetAsset.updateMany({ where: filter, data: { labels } })
      else await tx.promptTemplateAsset.updateMany({ where: filter, data: { labels } })
    })
  }

  /** 从同资产、非目标版本上摘除指定互斥标签（事务内调用）。 */
  private async _stripLabelsFromOthers(
    tx: Prisma.TransactionClient,
    kind: "rule-sets" | "prompts" | "datasets",
    scenarioId: string,
    assetId: string,
    version: string,
    labels: string[],
  ): Promise<void> {
    const whereOther = { scenarioId, assetId, NOT: { version } }
    const select = { id: true, labels: true }
    let others: Array<{ id: string; labels: string[] }>
    if (kind === "rule-sets") {
      others = await tx.ruleSetAsset.findMany({ where: whereOther, select })
    } else if (kind === "datasets") {
      others = await tx.datasetAsset.findMany({ where: whereOther, select })
    } else {
      others = await tx.promptTemplateAsset.findMany({ where: whereOther, select })
    }
    for (const o of others) {
      if (!o.labels.some((l) => labels.includes(l))) continue
      const cleaned = o.labels.filter((l) => !labels.includes(l))
      if (kind === "rule-sets") await tx.ruleSetAsset.update({ where: { id: o.id }, data: { labels: cleaned } })
      else if (kind === "datasets") await tx.datasetAsset.update({ where: { id: o.id }, data: { labels: cleaned } })
      else await tx.promptTemplateAsset.update({ where: { id: o.id }, data: { labels: cleaned } })
    }
  }

  async getCatalog(scenarioId: string): Promise<ScenarioCatalog | null> {
    const scenario = await this.prisma.scenario.findUnique({ where: { id: scenarioId } })
    if (!scenario) return null

    const [ruleSets, prompts, datasets] = await Promise.all([
      this.prisma.ruleSetAsset.findMany({ where: { scenarioId } }),
      this.prisma.promptTemplateAsset.findMany({ where: { scenarioId } }),
      this.prisma.datasetAsset.findMany({ where: { scenarioId } }),
    ])

    return {
      scenario: { id: scenario.id, name: scenario.name, description: scenario.description },
      rule_sets: pickLatestPerAsset(ruleSets).map((r) => this._toEntry(r)),
      prompts: pickLatestPerAsset(prompts).map((p) => this._toEntry(p)),
      datasets: pickLatestPerAsset(datasets).map((d) => ({
        ...this._toEntry(d),
        role: d.role,
        backend_type: d.backendType,
      })),
    }
  }

  private _toEntry(r: {
    assetId: string
    version: string
    labels: string[]
    content: unknown
  }): CatalogEntry {
    const c = (r.content ?? {}) as Record<string, unknown>
    return {
      asset_id: r.assetId,
      version: r.version,
      labels: r.labels,
      name: (c.name as string) ?? null,
      description: (c.description as string) ?? null,
    }
  }
}
