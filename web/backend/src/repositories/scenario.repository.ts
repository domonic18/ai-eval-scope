/**
 * 场景包配置资产读取（Phase 3，对齐 13 §11.2）。
 *
 * 替代构建期静态 rule-sets.json：从 scenarios / *_assets 表动态组装 catalog。
 * 资产按 (scenarioId, assetId, version) 唯一；catalog 默认返回每个 assetId 的最新版本
 * （labels 含 production 优先，否则最高版本）。
 */

import { createHash } from "crypto"
import type { PrismaClient } from "@prisma/client"
import { getPrisma } from "../infra/prisma"

function hashContent(content: unknown): string {
  return "sha256:" + createHash("sha256").update(JSON.stringify(content)).digest("hex")
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
      const created = await tx.scenarioPackage.upsert({
        where: { scenarioId_assetId_version: { scenarioId, assetId: input.assetId, version: input.version } },
        update: {
          labels: input.labels ?? [],
          content: input.content as never,
          contentHash,
        },
        create: {
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

  /** 发布/更新一个规则集资产版本（幂等 upsert）。 */
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
    await this.prisma.ruleSetAsset.upsert({
      where: { scenarioId_assetId_version: { scenarioId, assetId: input.assetId, version: input.version } },
      update: { labels: input.labels ?? [], content: input.content as never, contentHash },
      create: {
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

  /** 发布/更新一个提示词资产版本（幂等 upsert）。 */
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
    await this.prisma.promptTemplateAsset.upsert({
      where: {
        scenarioId_namespace_assetId_version: { scenarioId, namespace, assetId: input.assetId, version: input.version },
      },
      update: { labels: input.labels ?? [], content: input.content as never, contentHash },
      create: {
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

  /** 发布/更新一个数据集资产版本（幂等 upsert）。 */
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
    await this.prisma.datasetAsset.upsert({
      where: { scenarioId_assetId_version: { scenarioId, assetId: input.assetId, version: input.version } },
      update: {
        labels: input.labels ?? [],
        role: input.role,
        backendType: input.backendType,
        backendConfig: input.backendConfig as never,
        content: input.content as never,
        contentHash,
      },
      create: {
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
    const latest = this._latestPerAsset(rows)[0]
    return latest.content as Record<string, unknown>
  }

  /** 标签晋升：覆盖某资产版本的 labels（P4-5 标签晋升）。 */
  async setAssetLabels(
    scenarioId: string,
    kind: "rule-sets" | "prompts" | "datasets",
    assetId: string,
    version: string,
    labels: string[],
  ): Promise<void> {
    // updateMany 不支持复合唯一键快捷式，按字段 AND 过滤
    const filter = { scenarioId, assetId, version }
    if (kind === "rule-sets") {
      await this.prisma.ruleSetAsset.updateMany({ where: filter, data: { labels } })
    } else if (kind === "datasets") {
      await this.prisma.datasetAsset.updateMany({ where: filter, data: { labels } })
    } else {
      await this.prisma.promptTemplateAsset.updateMany({ where: filter, data: { labels } })
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
      rule_sets: this._latestPerAsset(ruleSets).map((r) => this._toEntry(r)),
      prompts: this._latestPerAsset(prompts).map((p) => this._toEntry(p)),
      datasets: this._latestPerAsset(datasets).map((d) => ({
        ...this._toEntry(d),
        role: d.role,
        backend_type: d.backendType,
      })),
    }
  }

  /** 每个 assetId 取一条：production 标签优先，否则最高版本。 */
  private _latestPerAsset<T extends { assetId: string; version: string; labels: string[] }>(
    rows: T[],
  ): T[] {
    const byAsset = new Map<string, T[]>()
    for (const r of rows) {
      const arr = byAsset.get(r.assetId) ?? []
      arr.push(r)
      byAsset.set(r.assetId, arr)
    }
    const out: T[] = []
    for (const arr of byAsset.values()) {
      arr.sort((a, b) => this._rank(b) - this._rank(a) || this._cmpVersion(b.version, a.version))
      out.push(arr[0])
    }
    return out
  }

  private _rank(r: { labels: string[] }): number {
    if (r.labels.includes("production")) return 3
    if (r.labels.includes("staging")) return 2
    if (r.labels.includes("latest")) return 1
    return 0
  }

  private _cmpVersion(a: string, b: string): number {
    const pa = a.split(".").map((n) => parseInt(n, 10) || 0)
    const pb = b.split(".").map((n) => parseInt(n, 10) || 0)
    for (let i = 0; i < 3; i++) {
      const d = (pa[i] ?? 0) - (pb[i] ?? 0)
      if (d !== 0) return d
    }
    return 0
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
