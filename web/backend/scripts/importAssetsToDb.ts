/**
 * 场景包资产导入脚本（Phase 4，对齐 13 §5.3 文件→DB）。
 *
 * 读取任意场景包（默认 evaluator 内置 courseware 包；PACKAGE_DIR 可指向其它包），
 * 把规则/提示词/数据集（参考知识）+ defaults(指标定义/聚合策略) + 场景包本体导入 Web 配置资产表，
 * 使动态 catalog 有真实数据。幂等：按 (scenarioId, assetId, version) upsert，可安全重跑。
 *
 * scenario_id / version / name / description 均从包内 agent_eval.yaml 的 package 段读取（去 courseware 硬编码）。
 *
 * 用法：npx tsx scripts/importAssetsToDb.ts [--package-dir <path>]
 *   PACKAGE_DIR 环境变量亦可指定包根（默认仓库内 evaluator 内置 courseware 包）。
 */

import { createHash } from "crypto"
import { existsSync, readFileSync, readdirSync, statSync } from "fs"
import { join, relative, resolve } from "path"
import yaml from "js-yaml"
import type { PrismaClient } from "@prisma/client"
import { ScenarioRepository } from "../src/repositories/scenario.repository"

const DEFAULT_SCENARIO_ID = "courseware"
const DEFAULT_VERSION = "1.0.0"

function defaultPackageDir(): string {
  // __dirname = web/backend/scripts → 仓库根为 ../../../
  return resolve(__dirname, "../../../evaluator/agent_eval/assets/packages/courseware", DEFAULT_VERSION)
}

function hash(obj: unknown): string {
  return "sha256:" + createHash("sha256").update(JSON.stringify(obj)).digest("hex")
}

function loadYaml(file: string): Record<string, unknown> {
  return (yaml.load(readFileSync(file, "utf-8")) ?? {}) as Record<string, unknown>
}

/** 递归收集包内 rules/prompts/datasets 的 yaml 文件为 { 相对路径: 文本 }（S2-1，供 executor 拉取）。 */
function collectPackageFiles(packageDir: string): Record<string, string> {
  const out: Record<string, string> = {}
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name)
      if (statSync(p).isDirectory()) walk(p)
      else if (name.endsWith(".yaml") || name.endsWith(".yml")) {
        out[relative(packageDir, p)] = readFileSync(p, "utf-8")
      }
    }
  }
  for (const sub of ["rules", "prompts", "datasets", "task_sets", "sut_configs"]) {
    const d = join(packageDir, sub)
    if (existsSync(d)) walk(d)
  }
  return out
}

export interface ImportResult {
  scenarioId: string
  ruleSets: number
  prompts: number
  datasets: number
  taskSets: number
  sutConfigs: number
}

/** 导入场景包资产到 DB（scenario/version/name 从 manifest 读取，任意场景通用）。 */
export async function importScenarioPackage(
  prisma: PrismaClient,
  packageDir: string = defaultPackageDir(),
): Promise<ImportResult> {
  // 从 agent_eval.yaml 的 package 段读 scenario/version/name/description（去硬编码）
  const manifest = loadYaml(join(packageDir, "agent_eval.yaml"))["package"] as Record<string, unknown>
  const SCENARIO_ID = String(manifest.scenario ?? DEFAULT_SCENARIO_ID)
  const VERSION = String(manifest.version ?? DEFAULT_VERSION)
  const SCENARIO_NAME = String(manifest.name ?? SCENARIO_ID)
  const SCENARIO_DESC = String(manifest.description ?? "")

  // #60：从包内 metrics/policy.yaml 读取指标定义 + 聚合策略（跨语言单一源）
  const policyPath = join(packageDir, "metrics", "policy.yaml")
  const policy = loadYaml(policyPath) as {
    metric_definitions: Record<string, unknown>[]
    aggregation_policy: Record<string, unknown>
  }
  // 场景行（name/description）
  await prisma.scenario.upsert({
    where: { id: SCENARIO_ID },
    update: { name: SCENARIO_NAME, description: SCENARIO_DESC },
    create: { id: SCENARIO_ID, name: SCENARIO_NAME, description: SCENARIO_DESC },
  })
  // defaults 版本化：发布（assetId=default）；已存在则跳过（幂等，不覆盖不可变版本）
  const existingDefaults = await prisma.defaultsAsset.findUnique({
    where: { scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: "default", version: VERSION } },
    select: { id: true },
  })
  if (!existingDefaults) {
    await new ScenarioRepository(prisma).publishDefaultsAsset(SCENARIO_ID, {
      version: VERSION,
      labels: ["latest", "production"],
      content: {
        metric_definitions: policy.metric_definitions ?? [],
        aggregation_policy: policy.aggregation_policy ?? null,
      },
      createdBy: "import-script",
    })
  }

  const labels = ["production", "latest"]
  // S2-1：发布 {manifest, files}（executor 运行时拉取所需结构，ADR-01）
  const files = collectPackageFiles(packageDir)
  const packageContent = { manifest: manifest ?? {}, files }
  await prisma.scenarioPackage.upsert({
    where: { scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: SCENARIO_ID, version: VERSION } },
    update: { labels, content: packageContent as never, contentHash: hash(packageContent) },
    create: {
      scenarioId: SCENARIO_ID,
      assetId: SCENARIO_ID,
      version: VERSION,
      labels,
      content: packageContent as never,
      contentHash: hash(packageContent),
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
        role: "reference", // 参考知识库 → role=reference
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

  // 考卷与 SUT 接入（arch/16 §2.1 包内资产）：task_sets/ 按文件 stem、
  // sut_configs/ 按 sut.name；与 rules 等同款 upsert 幂等
  const taskSets = await importDir(packageDir, "task_sets", async (stem, content) => {
    await prisma.taskSetAsset.upsert({
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

  const sutConfigs = await importDir(packageDir, "sut_configs", async (_stem, content) => {
    const sut = content.sut as Record<string, unknown> | undefined
    if (!sut || !sut.name) throw new Error(`sut_config 缺少 sut:/sut.name: ${JSON.stringify(_stem)}`)
    await prisma.sutConfigAsset.upsert({
      where: {
        scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: String(sut.name), version: VERSION },
      },
      update: { labels, content: sut as never, contentHash: hash(sut) },
      create: {
        scenarioId: SCENARIO_ID,
        packageId: SCENARIO_ID,
        assetId: String(sut.name),
        version: VERSION,
        labels,
        content: sut as never,
        contentHash: hash(sut),
        createdBy: "import-script",
      },
    })
  })

  return { scenarioId: SCENARIO_ID, ruleSets, prompts, datasets, taskSets, sutConfigs }
}

/** 导入一个子目录的 yaml 资产；目录不存在则跳过（返回 0）。 */
async function importDir(
  packageDir: string,
  sub: string,
  fn: (stem: string, content: Record<string, unknown>) => Promise<void>,
): Promise<number> {
  const dir = join(packageDir, sub)
  if (!existsSync(dir)) return 0
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
    const res = await importScenarioPackage(prisma, pkgDir)
    console.log("✅ 场景包导入完成：", res)
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
