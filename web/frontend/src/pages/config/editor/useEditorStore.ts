/**
 * 统一编辑器 Store（docs/arch/13配置管理设计.md §6.3）。
 *
 * - docs：每资产一份内存编辑态，切换 Tab/树不丢未保存内容；
 * - selection 经 URL `?select=` 驱动（可分享/刷新/前进后退）；
 * - localStorage 草稿仅作刷新兜底，恢复须用户显式确认（pendingDraft）；
 * - 新建资产为本地 isNew 草稿，不向服务端发骨架版本；发布时做引用完整性校验 + 可批量发布引用。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import * as yaml from "js-yaml"
import { toast } from "sonner"
import {
  api,
  type AssetKind,
  type CatalogEntry,
  type DatasetCatalogEntry,
  type ScenarioCatalog,
} from "../../../api/client"
import { createEmptyDataset, createEmptyPrompt, createEmptyRuleSet } from "../forms/defaults"
import {
  draftKeyOf,
  errMsg,
  parseSelection,
  SPECIAL_SELECTIONS,
  type DocState,
  type Selection,
} from "./types"

export interface Catalog {
  rule_sets: CatalogEntry[]
  prompts: CatalogEntry[]
  datasets: DatasetCatalogEntry[]
}

export type Dict = Record<string, unknown>
const selOf = (kind: AssetKind, assetId: string): Selection => `${kind}:${assetId}`
const newAssetId = (prefix: string) => `${prefix}_${Date.now().toString(36).slice(-5)}`

export function useEditorStore(scenarioId: string) {
  const [searchParams, setSearchParams] = useSearchParams()
  const selected: Selection | null = searchParams.get("select")
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [docs, setDocs] = useState<Record<Selection, DocState>>({})
  const [tabs, setTabs] = useState<Selection[]>([])
  const [diff, setDiff] = useState<{ version: string; content: string } | null>(null)
  const [busy, setBusy] = useState(false)

  // ── 选择（URL 驱动）──
  const select = useCallback(
    (sel: Selection | null, opts?: { replace?: boolean }) => {
      setDiff(null)
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (sel) next.set("select", sel)
          else next.delete("select")
          return next
        },
        { replace: opts?.replace ?? false },
      )
    },
    [setSearchParams],
  )

  // ── catalog 加载 ──
  const reloadCatalog = useCallback(async () => {
    try {
      const c: ScenarioCatalog = await api.scenarioCatalog(scenarioId)
      setCatalog({ rule_sets: c.rule_sets, prompts: c.prompts, datasets: c.datasets })
    } catch {
      setCatalog({ rule_sets: [], prompts: [], datasets: [] })
    }
  }, [scenarioId])

  useEffect(() => {
    reloadCatalog()
  }, [reloadCatalog])

  // 默认选中：无 select 参数时取第一个规则集
  useEffect(() => {
    if (selected || !catalog) return
    if (catalog.rule_sets.length > 0) {
      select(selOf("rule-sets", catalog.rule_sets[0].asset_id), { replace: true })
    }
  }, [catalog, selected, select])

  // ── 文档加载（含草稿检测，恢复须显式确认）──
  const loadDoc = useCallback(
    async (kind: AssetKind, assetId: string) => {
      const key = selOf(kind, assetId)
      try {
        const c = await api.assetContent(scenarioId, kind, assetId)
        if (kind === "datasets" && !c.role) c.role = "reference"
        const baselineYaml = yaml.dump(c, { sortKeys: false })
        // 检测 localStorage 草稿：存在且与已发布不同 → 待用户确认，不静默覆盖
        let pendingDraft: Dict | null = null
        try {
          const raw = localStorage.getItem(draftKeyOf(scenarioId, kind, assetId))
          if (raw) {
            const d = JSON.parse(raw)
            if (
              d?.content &&
              typeof d.content === "object" &&
              yaml.dump(d.content, { sortKeys: false }) !== baselineYaml
            ) {
              pendingDraft = d.content as Dict
            }
          }
        } catch {
          /* 草稿损坏忽略 */
        }
        let versions: DocState["versions"] = []
        try {
          versions = await api.listAssetVersions(scenarioId, kind, assetId)
        } catch {
          /* 忽略 */
        }
        setDocs((prev) => ({
          ...prev,
          [key]: {
            kind,
            assetId,
            content: c,
            baselineYaml,
            nextVersion: versions[0]?.version ?? "1.0.0",
            versions,
            pendingDraft,
          },
        }))
      } catch {
        setDocs((prev) => ({
          ...prev,
          [key]: { kind, assetId, content: null, baselineYaml: "", nextVersion: "0.1.0", versions: [] },
        }))
      }
    },
    [scenarioId],
  )

  // 选中资产文档不存在则加载；同时维护 tabs。
  // 注意：仅在内存中无该文档时加载——切回已打开/本地新建(isNew)资产不得重拉覆盖未保存编辑。
  const docsRef = useRef(docs)
  docsRef.current = docs
  useEffect(() => {
    if (!selected || SPECIAL_SELECTIONS.includes(selected as (typeof SPECIAL_SELECTIONS)[number])) return
    const parsed = parseSelection(selected)
    if (!parsed) return
    setTabs((prev) => (prev.includes(selected) ? prev : [...prev, selected]))
    if (docsRef.current[selected]) return
    setDocs((prev) => {
      if (prev[selected]) return prev
      return { ...prev, [selected]: { kind: parsed.kind, assetId: parsed.assetId, content: null, baselineYaml: "", nextVersion: "0.1.0", versions: [] } }
    })
    loadDoc(parsed.kind, parsed.assetId)
  }, [selected, loadDoc])

  // ── 编辑：更新内容（内存态），防抖落 localStorage 草稿兜底 ──
  const updateDoc = useCallback((sel: Selection, content: Dict) => {
    setDocs((prev) => {
      const doc = prev[sel]
      if (!doc) return prev
      return { ...prev, [sel]: { ...doc, content, pendingDraft: null } }
    })
  }, [])

  const dirtyOf = useCallback(
    (sel: Selection): boolean => {
      const doc = docs[sel]
      if (!doc || doc.content == null) return false
      return yaml.dump(doc.content, { sortKeys: false }) !== doc.baselineYaml || !!doc.isNew
    },
    [docs],
  )

  const setNextVersion = useCallback((sel: Selection, v: string) => {
    setDocs((prev) => {
      const doc = prev[sel]
      if (!doc) return prev
      return { ...prev, [sel]: { ...doc, nextVersion: v } }
    })
  }, [])

  // 草稿兜底：docs 变化后防抖写入（仅 dirty 文档）
  useEffect(() => {
    const t = setTimeout(() => {
      for (const [sel, doc] of Object.entries(docsRef.current)) {
        const parsed = parseSelection(sel)
        if (!parsed || doc.content == null) continue
        const key = draftKeyOf(scenarioId, parsed.kind, parsed.assetId)
        const dirty = yaml.dump(doc.content, { sortKeys: false }) !== doc.baselineYaml || !!doc.isNew
        try {
          if (dirty) {
            localStorage.setItem(key, JSON.stringify({ content: doc.content, savedAt: new Date().toISOString() }))
          } else {
            localStorage.removeItem(key)
          }
        } catch {
          /* 忽略 */
        }
      }
    }, 600)
    return () => clearTimeout(t)
  }, [docs, scenarioId])

  // ── 草稿显式恢复 / 忽略 ──
  const restoreDraft = useCallback((sel: Selection) => {
    setDocs((prev) => {
      const doc = prev[sel]
      if (!doc?.pendingDraft) return prev
      const dc = doc.pendingDraft
      if (doc.kind === "datasets" && !dc.role) dc.role = "reference"
      return { ...prev, [sel]: { ...doc, content: dc, pendingDraft: null } }
    })
    toast.info("已恢复本地草稿（基线仍为已发布版本，发布后才生效）")
  }, [])

  const discardDraft = useCallback(
    (sel: Selection) => {
      const parsed = parseSelection(sel)
      if (parsed) localStorage.removeItem(draftKeyOf(scenarioId, parsed.kind, parsed.assetId))
      setDocs((prev) => {
        const doc = prev[sel]
        if (!doc) return prev
        return { ...prev, [sel]: { ...doc, pendingDraft: null } }
      })
    },
    [scenarioId],
  )

  // ── 新建资产（本地 isNew 草稿，不发服务端骨架）──
  const createAsset = useCallback(
    (kind: AssetKind): Selection => {
      const prefix = kind === "prompts" ? "prompt" : kind === "datasets" ? "dataset" : "ruleset"
      const assetId = newAssetId(prefix)
      const content =
        kind === "prompts"
          ? (createEmptyPrompt(assetId) as unknown as Dict)
          : kind === "datasets"
            ? (createEmptyDataset() as unknown as Dict)
            : (createEmptyRuleSet(assetId, scenarioId) as unknown as Dict)
      const key = selOf(kind, assetId)
      setDocs((prev) => ({
        ...prev,
        [key]: {
          kind,
          assetId,
          content,
          baselineYaml: yaml.dump(content, { sortKeys: false }),
          isNew: true,
          nextVersion: "0.1.0",
          versions: [],
        },
      }))
      select(key)
      return key
    },
    [scenarioId, select],
  )

  /** 新建提示词并绑定到指定规则字段（规则卡片回调） */
  const createAndBindPrompt = useCallback(
    (ruleSel: Selection, ruleIndex: number, field: "prompt_id" | "confirmation_prompt_id") => {
      const key = createAsset("prompts")
      const assetId = parseSelection(key)!.assetId
      setDocs((prev) => {
        const doc = prev[ruleSel]
        if (!doc?.content) return prev
        const rules = ((doc.content as Dict).rules as Dict[]).map((r, i) =>
          i === ruleIndex ? { ...r, [field]: assetId } : r,
        )
        return { ...prev, [ruleSel]: { ...doc, content: { ...doc.content, rules } } }
      })
      toast.success(`已新建提示词 ${assetId} 并绑定到规则`)
    },
    [createAsset],
  )

  // ── 引用完整性校验（规则集发布前）──
  const missingRefs = useCallback(
    (sel: Selection): { prompts: string[]; datasets: string[]; unpublished: Selection[] } => {
      const doc = docs[sel]
      const out = { prompts: [] as string[], datasets: [] as string[], unpublished: [] as Selection[] }
      if (!doc || doc.kind !== "rule-sets" || !doc.content) return out
      const rules = ((doc.content as Dict).rules as Dict[]) ?? []
      const promptIds = new Set<string>()
      const datasetIds = new Set<string>()
      // 按 method 决定哪些绑定字段参与校验（对齐 RuleCard 条件化渲染与 evaluator 模型）：
      // 仅 llm/llm_vision/rule_set 的 prompt_id、rule_set 的 confirmation_prompt_id/dataset_ids 才算资产引用；
      // format 规则残留的 prompt_id/dataset_id 等不参与（UI 不渲染、评估器也不用）。
      for (const r of rules) {
        const method = r.method as string | undefined
        const prompt_id = r.prompt_id as string | undefined
        const confirmation_prompt_id = r.confirmation_prompt_id as string | undefined
        const dataset_ids = r.dataset_ids as string[] | undefined
        if (method === "llm" || method === "llm_vision" || method === "rule_set") {
          if (prompt_id) promptIds.add(prompt_id)
        }
        if (method === "rule_set") {
          if (confirmation_prompt_id) promptIds.add(confirmation_prompt_id)
          for (const d of dataset_ids ?? []) datasetIds.add(d)
        }
      }
      const catalogPrompts = new Set((catalog?.prompts ?? []).map((p) => p.asset_id))
      const catalogDatasets = new Set((catalog?.datasets ?? []).map((d) => d.asset_id))
      for (const p of promptIds) {
        if (catalogPrompts.has(p)) continue
        const key = selOf("prompts", p)
        if (docs[key]?.isNew) out.unpublished.push(key)
        else out.prompts.push(p)
      }
      for (const d of datasetIds) {
        if (catalogDatasets.has(d)) continue
        const key = selOf("datasets", d)
        if (docs[key]?.isNew) out.unpublished.push(key)
        else out.datasets.push(d)
      }
      return out
    },
    [docs, catalog],
  )

  // ── 发布 ──
  const publish = useCallback(
    async (sel: Selection, labels: string[], opts?: { withRefs?: boolean }) => {
      const doc = docs[sel]
      if (!doc?.content) return false
      setBusy(true)
      try {
        if (doc.kind === "rule-sets") {
          const refs = missingRefs(sel)
          if (refs.prompts.length || refs.datasets.length) {
            toast.error(
              `引用的资产不存在：${[...refs.prompts.map((p) => `提示词 ${p}`), ...refs.datasets.map((d) => `数据集 ${d}`)].join("、")}`,
            )
            return false
          }
          if (refs.unpublished.length && !opts?.withRefs) {
            toast.error("存在未发布的引用资产，请选择「连同引用一起发布」")
            return false
          }
          // 批量：先发 isNew 引用资产
          for (const refSel of refs.unpublished) {
            const refDoc = docs[refSel]
            if (!refDoc?.content) continue
            await api.publishAsset(scenarioId, refDoc.kind, {
              asset_id: refDoc.assetId,
              version: refDoc.nextVersion || "0.1.0",
              labels: [],
              content: refDoc.content,
              ...(refDoc.kind === "datasets"
                ? { role: ((refDoc.content as Dict).role as string) ?? "reference", backend_type: ((refDoc.content as Dict).backend_type as string) ?? "yaml_file" }
                : {}),
            })
            const parsed = parseSelection(refSel)!
            localStorage.removeItem(draftKeyOf(scenarioId, parsed.kind, parsed.assetId))
            setDocs((prev) => ({
              ...prev,
              [refSel]: { ...prev[refSel], isNew: false, baselineYaml: yaml.dump(prev[refSel].content, { sortKeys: false }) },
            }))
          }
        }
        await api.publishAsset(scenarioId, doc.kind, {
          asset_id: doc.assetId,
          version: doc.nextVersion,
          labels,
          content: doc.content,
          ...(doc.kind === "datasets"
            ? { role: ((doc.content as Dict).role as string) ?? "reference", backend_type: ((doc.content as Dict).backend_type as string) ?? "yaml_file" }
            : {}),
        })
        const parsed = parseSelection(sel)!
        localStorage.removeItem(draftKeyOf(scenarioId, parsed.kind, parsed.assetId))
        const versions = await api.listAssetVersions(scenarioId, doc.kind, doc.assetId).catch(() => [])
        setDocs((prev) => ({
          ...prev,
          [sel]: {
            ...prev[sel],
            isNew: false,
            baselineYaml: yaml.dump(prev[sel].content, { sortKeys: false }),
            versions,
          },
        }))
        await reloadCatalog()
        toast.success(`已发布 ${doc.assetId}@${doc.nextVersion}`)
        return true
      } catch (e) {
        toast.error(errMsg(e, "发布失败"))
        return false
      } finally {
        setBusy(false)
      }
    },
    [docs, missingRefs, reloadCatalog, scenarioId],
  )

  // ── 标签晋升 / 版本对比 ──
  const promote = useCallback(
    async (sel: Selection, ver: string, lbl: string) => {
      const parsed = parseSelection(sel)
      if (!parsed) return
      try {
        await api.promoteAssetLabels(scenarioId, parsed.kind, parsed.assetId, ver, [lbl])
        toast.success(`${ver} 已晋升为 ${lbl}`)
        const versions = await api.listAssetVersions(scenarioId, parsed.kind, parsed.assetId)
        setDocs((prev) => ({ ...prev, [sel]: { ...prev[sel], versions } }))
      } catch (e) {
        toast.error(errMsg(e, "晋升失败"))
      }
    },
    [scenarioId],
  )

  const showDiff = useCallback(
    async (sel: Selection, ver: string) => {
      if (diff?.version === ver) {
        setDiff(null)
        return
      }
      const parsed = parseSelection(sel)
      if (!parsed) return
      try {
        const old = await api.assetContent(scenarioId, parsed.kind, parsed.assetId, ver)
        setDiff({ version: ver, content: yaml.dump(old, { sortKeys: false }) })
      } catch {
        toast.error("获取版本内容失败")
      }
    },
    [diff, scenarioId],
  )

  // ── Tab 关闭（文档保留在内存，dirty 不丢）──
  const closeTab = useCallback(
    (sel: Selection) => {
      setTabs((prev) => {
        const next = prev.filter((t) => t !== sel)
        if (selected === sel) select(next[next.length - 1] ?? null)
        return next
      })
    },
    [selected, select],
  )

  const doc = selected ? (docs[selected] ?? null) : null
  const dirty = selected ? dirtyOf(selected) : false
  const currentYaml = useMemo(
    () => (doc?.content ? yaml.dump(doc.content, { sortKeys: false }) : ""),
    [doc],
  )

  return {
    selected,
    select,
    catalog,
    reloadCatalog,
    docs,
    doc,
    tabs,
    closeTab,
    updateDoc,
    setNextVersion,
    dirty,
    dirtyOf,
    currentYaml,
    restoreDraft,
    discardDraft,
    createAsset,
    createAndBindPrompt,
    missingRefs,
    publish,
    busy,
    promote,
    diff,
    showDiff,
  }
}
