/**
 * 课程场景包资产导入脚本（Phase 3，对齐 13 §5.3 文件→DB）。
 *
 * 读取 evaluator 内置 courseware 包（agent_eval/assets/packages/courseware/<ver>/），
 * 把规则/提示词/数据集（参考知识）导入 Web 配置资产表，使动态 catalog 有真实数据。
 * 幂等：按 (scenarioId, assetId, version) upsert，可安全重跑。
 *
 * 用法：npx tsx scripts/importAssetsToDb.ts [--package-dir <path>]
 *   PACKAGE_DIR 环境变量亦可指定包根（默认仓库内 evaluator 内置 courseware 包）。
 */

import { createHash } from "crypto"
import { readFileSync, readdirSync } from "fs"
import { join, resolve } from "path"
import yaml from "js-yaml"
import type { PrismaClient } from "@prisma/client"

const SCENARIO_ID = "courseware"
const VERSION = "1.0.0"

function defaultPackageDir(): string {
  // __dirname = web/backend/scripts → 仓库根为 ../../../
  return resolve(__dirname, "../../../evaluator/agent_eval/assets/packages/courseware", VERSION)
}

function hash(obj: unknown): string {
  return "sha256:" + createHash("sha256").update(JSON.stringify(obj)).digest("hex")
}

function loadYaml(file: string): Record<string, unknown> {
  return (yaml.load(readFileSync(file, "utf-8")) ?? {}) as Record<string, unknown>
}

export interface ImportResult {
  scenarioId: string
  ruleSets: number
  prompts: number
  datasets: number
}

/** 导入 courseware 包资产到 DB。 */
export async function importCoursewarePackage(
  prisma: PrismaClient,
  packageDir: string = defaultPackageDir(),
): Promise<ImportResult> {
  await prisma.scenario.upsert({
    where: { id: SCENARIO_ID },
    update: {},
    create: { id: SCENARIO_ID, name: "课件质量评估", description: "课件生成场景默认包" },
  })

  const labels = ["production", "latest"]
  const manifestPath = join(packageDir, "agent_eval.yaml")
  const manifest = loadYaml(manifestPath)["package"] as Record<string, unknown> | undefined
  await prisma.scenarioPackage.upsert({
    where: { scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: SCENARIO_ID, version: VERSION } },
    update: { labels, content: (manifest ?? {}) as never, contentHash: hash(manifest ?? {}) },
    create: {
      scenarioId: SCENARIO_ID,
      assetId: SCENARIO_ID,
      version: VERSION,
      labels,
      content: (manifest ?? {}) as never,
      contentHash: hash(manifest ?? {}),
      createdBy: "import-script",
    },
  })

  const ruleSets = await importDir(packageDir, "rules", async (stem, content) => {
    await prisma.ruleSetAsset.upsert({
      where: { scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: stem, version: VERSION } },
      update: { labels, content: content as never, contentHash: hash(content) },
      create: {
        scenarioId: SCENARIO_ID,
        packageId: SCENARIO_ID,
        assetId: stem,
        version: VERSION,
        labels,
        content: content as never,
        contentHash: hash(content),
        createdBy: "import-script",
      },
    })
  })

  const prompts = await importDir(packageDir, "prompts", async (stem, content) => {
    const assetId = (content.template_id as string) || stem
    const namespace = (content.namespace as string) || SCENARIO_ID
    await prisma.promptTemplateAsset.upsert({
      where: {
        scenarioId_namespace_assetId_version: {
          scenarioId: SCENARIO_ID,
          namespace,
          assetId,
          version: VERSION,
        },
      },
      update: { labels, content: content as never, contentHash: hash(content) },
      create: {
        scenarioId: SCENARIO_ID,
        packageId: SCENARIO_ID,
        assetId,
        namespace,
        version: VERSION,
        labels,
        content: content as never,
        contentHash: hash(content),
        createdBy: "import-script",
      },
    })
  })

  const datasets = await importDir(packageDir, "datasets", async (stem, content) => {
    await prisma.datasetAsset.upsert({
      where: { scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: stem, version: VERSION } },
      update: { labels, content: content as never, contentHash: hash(content) },
      create: {
        scenarioId: SCENARIO_ID,
        packageId: SCENARIO_ID,
        assetId: stem,
        role: "reference", // 课件知识点库 → role=reference
        version: VERSION,
        labels,
        backendType: "yaml_file",
        backendConfig: { file: `${stem}.yaml` } as never,
        content: content as never,
        contentHash: hash(content),
        createdBy: "import-script",
      },
    })
  })

  return { scenarioId: SCENARIO_ID, ruleSets, prompts, datasets }
}

async function importDir(
  packageDir: string,
  sub: string,
  fn: (stem: string, content: Record<string, unknown>) => Promise<void>,
): Promise<number> {
  const dir = join(packageDir, sub)
  let n = 0
  for (const f of readdirSync(dir).filter((x) => x.endsWith(".yaml"))) {
    const stem = f.replace(/\.ya?ml$/, "")
    await fn(stem, loadYaml(join(dir, f)))
    n++
  }
  return n
}

async function main() {
  const { PrismaClient } = await import("@prisma/client")
  const prisma = new PrismaClient()
  const pkgDir = process.env.PACKAGE_DIR || defaultPackageDir()
  try {
    const res = await importCoursewarePackage(prisma, pkgDir)
    console.log("✅ 课程场景包导入完成：", res)
  } finally {
    await prisma.$disconnect()
  }
}

const invokedDirectly =
  typeof process !== "undefined" && !!process.argv[1]?.includes("importAssetsToDb.ts")
if (invokedDirectly) {
  main().catch((e) => {
    console.error("❌ 导入失败：", e)
    process.exit(1)
  })
}
