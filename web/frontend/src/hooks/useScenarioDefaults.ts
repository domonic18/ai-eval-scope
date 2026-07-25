/**
 * 场景默认指标定义 hook（模块级缓存，多页面共享一次 fetch）。
 *
 * 指标定义统一来自后端 GET /scenarios/:id/defaults（单一源落库，由 import 脚本写入）。
 */
import { useEffect, useState } from "react"
import { api } from "../api/client"
import type { MetricDef } from "../types"

const _cache = new Map<string, MetricDef[]>()

/** 按场景 id 拉取默认指标定义（命中模块缓存即返回缓存值，不重复请求）。 */
function fetchScenarioDefaults(scenarioId: string): Promise<MetricDef[]> {
  if (_cache.has(scenarioId)) return Promise.resolve(_cache.get(scenarioId)!)
  return api.scenarioDefaults(scenarioId).then((d) => {
    _cache.set(scenarioId, d)
    return d
  })
}

/** 单场景指标定义（scenarioId 必传，无 courseware 默认）。 */
export function useScenarioDefaults(scenarioId: string): MetricDef[] {
  const [defs, setDefs] = useState<MetricDef[]>(_cache.get(scenarioId) ?? [])
  useEffect(() => {
    fetchScenarioDefaults(scenarioId)
      .then(setDefs)
      .catch(() => {})
  }, [scenarioId])
  return defs
}

/**
 * 多场景指标定义映射：对 distinct 场景逐个按需拉取（复用 _cache），
 * 返回 { scenarioId: defs }。供 Dashboard（多项目）/ AdminRuns（多场景）等
 * 跨场景列表页按各行/各卡各自场景取 defs。
 */
export function useScenarioDefaultsMap(scenarioIds: string[]): Record<string, MetricDef[]> {
  const [map, setMap] = useState<Record<string, MetricDef[]>>(() => {
    const m: Record<string, MetricDef[]> = {}
    for (const id of scenarioIds) {
      const cached = _cache.get(id)
      if (cached) m[id] = cached
    }
    return m
  })
  const key = scenarioIds.join(",")
  useEffect(() => {
    const ids = key ? key.split(",") : []
    const missing = ids.filter((id) => !_cache.has(id))
    if (missing.length === 0) {
      const m: Record<string, MetricDef[]> = {}
      for (const id of ids) m[id] = _cache.get(id)!
      setMap(m)
      return
    }
    let cancelled = false
    Promise.all(missing.map((id) => fetchScenarioDefaults(id).then((d) => [id, d] as const)))
      .then((entries) => {
        if (cancelled) return
        setMap((prev) => {
          const m = { ...prev }
          for (const [id, d] of entries) m[id] = d
          return m
        })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [key])
  return map
}
