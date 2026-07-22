/**
 * 统一编辑器类型定义（docs/arch/13配置管理设计.md）。
 *
 * Selection 编码进 URL query（`?select=<kind>:<assetId>`），刷新/分享/前进后退天然正确。
 * 每个资产在内存中持有一份 DocState，切换不丢未保存内容；localStorage 草稿仅作刷新兜底，
 * 恢复必须经用户显式确认，绝不静默覆盖已发布内容。
 */
import type { AssetKind } from "../../../api/client"

/** 可选中对象：`rule-sets:x` / `prompts:y` / `datasets:z` / `policy` / `metrics` */
export type Selection = string
export const SPECIAL_SELECTIONS = ["policy", "metrics"] as const

export interface VersionInfo {
  version: string
  labels: string[]
  contentHash: string
  createdAt: string
}

/** 单个资产的编辑态 */
export interface DocState {
  kind: AssetKind
  assetId: string
  /** null = 加载中 */
  content: Record<string, unknown> | null
  /** 最近一次已发布/保存干净的 YAML 文本（dirty 判定基线） */
  baselineYaml: string
  /** 本地新建、尚未发布到服务端 */
  isNew?: boolean
  /** 下次发布的版本号（可在时间线面板修改） */
  nextVersion: string
  versions: VersionInfo[]
  /** 存在可恢复的 localStorage 草稿（等待用户显式确认） */
  pendingDraft?: Record<string, unknown> | null
}

export const parseSelection = (
  sel: Selection | null,
): { kind: AssetKind; assetId: string } | null => {
  if (!sel || SPECIAL_SELECTIONS.includes(sel as (typeof SPECIAL_SELECTIONS)[number])) return null
  const idx = sel.indexOf(":")
  if (idx <= 0) return null
  const kind = sel.slice(0, idx) as AssetKind
  const assetId = sel.slice(idx + 1)
  if (!assetId || !["rule-sets", "prompts", "datasets"].includes(kind)) return null
  return { kind, assetId }
}

export const draftKeyOf = (scenarioId: string, kind: AssetKind, assetId: string) =>
  `draft:${scenarioId}:${kind}:${assetId}`

export const VERSION_LABELS = ["production", "staging", "latest"]

export const errMsg = (e: unknown, fb: string) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb

/** 相对时间 + 日期，对齐原型 .vc-time */
export function relTime(iso: string): string {
  const d = new Date(iso)
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  const ago = days > 30 ? `${Math.floor(days / 30)}个月前` : days > 0 ? `${days}天前` : "今天"
  return `${ago} · ${d.toLocaleDateString("zh-CN")}`
}
