/**
 * 场景样本视图呈现配置（docs/arch/09 §9.7 配置链第一环）。
 *
 * 配置归属场景级（tab 语义随场景包形态走；多项目共享场景一处配置），管理端可编辑。
 * 词表 = 代码级固定词汇（同 metric id 性质），场景只做选择 / 排序 / 命名；
 * 读取链：配置存在按配置下发，null 时前端按制品证据机械兜底（web/frontend lib/artifactTabs.ts）。
 * 演进路径：evaluator 包清单未来可声明 sample_view，经既有导入 / run 补缺注册链写入同字段。
 */

import { Prisma } from "@prisma/client"
import { PlatformError } from "../middleware/errorHandler"
import { getPrisma } from "../infra/prisma"

/** tab 词表：证据族的机械对应物（doc=回答/原始文档 task=原始任务 transcript=会话过程 shot=截图 trace=执行链） */
export const SAMPLE_VIEW_TABS = ["doc", "task", "transcript", "shot", "trace"] as const
export type SampleViewTab = (typeof SAMPLE_VIEW_TABS)[number]

export interface SampleViewConfig {
  tabs: SampleViewTab[]
  /** tab 显示名覆盖（仅开放 doc——其语义随形态在「Agent 回答 / 原始文档」间切换） */
  labels?: { doc?: string }
}

/** 服务端校验：tabs ⊆ 词表、非空、去重的有序子集；labels.doc 可选非空字符串。未知键剥除。 */
export function parseSampleView(input: unknown): SampleViewConfig {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    throw new PlatformError("sample_view 必须为对象", { status: 400, code: "SCHEMA_INVALID" })
  }
  const raw = input as { tabs?: unknown; labels?: unknown }
  if (!Array.isArray(raw.tabs) || raw.tabs.length === 0) {
    throw new PlatformError("tabs 必须为非空数组", { status: 400, code: "SCHEMA_INVALID" })
  }
  const seen = new Set<string>()
  const tabs: SampleViewTab[] = []
  for (const t of raw.tabs) {
    if (typeof t !== "string" || !(SAMPLE_VIEW_TABS as readonly string[]).includes(t)) {
      throw new PlatformError(
        `非法 tab：${String(t)}（词表：${SAMPLE_VIEW_TABS.join("/")}）`,
        { status: 400, code: "SCHEMA_INVALID" },
      )
    }
    if (seen.has(t)) {
      throw new PlatformError(`tab 重复：${t}`, { status: 400, code: "SCHEMA_INVALID" })
    }
    seen.add(t)
    tabs.push(t as SampleViewTab)
  }
  const config: SampleViewConfig = { tabs }
  if (raw.labels !== undefined) {
    if (typeof raw.labels !== "object" || raw.labels === null || Array.isArray(raw.labels)) {
      throw new PlatformError("labels 必须为对象", { status: 400, code: "SCHEMA_INVALID" })
    }
    const doc = (raw.labels as { doc?: unknown }).doc
    if (doc !== undefined) {
      if (typeof doc !== "string" || !doc.trim()) {
        throw new PlatformError("labels.doc 必须为非空字符串", {
          status: 400,
          code: "SCHEMA_INVALID",
        })
      }
      config.labels = { doc }
    }
  }
  return config
}

/** 读取场景样本视图配置（未配置返回 null = 前端走机械兜底）。 */
export async function getScenarioSampleView(scenarioId: string): Promise<SampleViewConfig | null> {
  const row = await getPrisma().scenario.findUnique({
    where: { id: scenarioId },
    select: { sampleView: true },
  })
  if (!row) throw new PlatformError("scenario not found", { status: 404, code: "NOT_FOUND" })
  return (row.sampleView as SampleViewConfig | null) ?? null
}

/** 写入场景样本视图配置（整体替换；服务端校验先行）。 */
export async function setScenarioSampleView(
  scenarioId: string,
  input: unknown,
): Promise<SampleViewConfig> {
  const config = parseSampleView(input)
  const prisma = getPrisma()
  const scenario = await prisma.scenario.findUnique({
    where: { id: scenarioId },
    select: { id: true },
  })
  if (!scenario) throw new PlatformError("scenario not found", { status: 404, code: "NOT_FOUND" })
  await prisma.scenario.update({
    where: { id: scenarioId },
    data: { sampleView: config as unknown as Prisma.InputJsonValue },
  })
  return config
}
