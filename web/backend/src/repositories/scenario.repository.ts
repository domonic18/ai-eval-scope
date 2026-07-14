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
